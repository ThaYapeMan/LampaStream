#!/usr/bin/env python3
"""Offline LIGHTS-01 stream evidence using production DSP and the A/B scorer."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from replay_chain import decode  # noqa: E402

from lampastream.beat_accents import RelativeOnsetGate, select_events  # noqa: E402
from lampastream.canonicalizer import (  # noqa: E402
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    DecodedSourceFrame,
    EndOfStream,
)
from lampastream.models import Profile  # noqa: E402
from lampastream.player_manager import _make_canonical_pipeline  # noqa: E402
from lampastream.types import OnsetEnvelopeFrame  # noqa: E402

BREAKS = [(210, 212), (240, 242), (261, 262), (270, 272)]


def bench(path, out, reference=None, *, ceiling=64., floor=.3, estimate_tempo=False,
          k=2., window_s=3., refractory_ms=120., full_k=None):
    pcm, rate, fmt = decode(path)
    full_k = k+1 if full_k is None else full_k
    profile = Profile(agc_max_gain=ceiling, tracker_gain_floor=floor, onset_relative_k=k,
        onset_reference_window_s=window_s, onset_refractory_ms=refractory_ms, onset_full_k=full_k)
    onset_gate = RelativeOnsetGate(k, window_s, refractory_ms, full_k, profile.onset_delta_abs)
    pipeline = _make_canonical_pipeline(None, profile)
    pipeline._beat_fusion.gain_settings = profile.agc_max_gain, profile.tracker_gain_floor
    canonicalizer = AudioCanonicalizer()
    selected = {mode: [] for mode in ('onset', 'tracker')}
    maximum_gain = 0.
    gain_samples, raw_events, accepted_events, raw_frames = [], [], [], []

    def consume(records):
        nonlocal maximum_gain
        for record in records:
            maximum_gain = max(maximum_gain, record.features.agc_gain)
        for record in records:
            raw_events.extend(dict(time_s=e.candidate_sample/48000,
                strength=e.strength, strength_raw=e.strength_raw, gain=record.features.agc_gain,
                bass_strength=record.features.onset_bass_strength, bands=','.join(sorted(e.bands)),
                event_id=json.dumps(e.id), epoch=e.epoch)
                for e in record.features.diagnostic_events)
        raw_frames.extend(dict(epoch=record.epoch, sample_pos=frame.sample_pos,
            full=frame.full, bass=frame.bass, mid=frame.mid, treble=frame.treble)
            for record in records for frame in record.features.onset_raw_frames)
        for mode in selected:
            events = select_events(mode, [e for r in records for e in r.features.onset_events],
                                   records, gate=onset_gate)
            selected[mode].extend(events)
            if mode == "onset":
                accepted_events.extend(dict(time_s=e.candidate_sample/48000,
                    strength=e.strength, strength_raw=e.strength_raw) for e in events)
        pipeline.drain_publications()
        pipeline.drain_events()

    def feed(items):
        for item in items:
            if not isinstance(item, CanonicalData):
                continue
            frame = item.frame
            for offset in range(0, len(frame.samples), 480):
                start = frame.sample_pos+offset
                consume(pipeline.feed(replace(frame,
                    samples=frame.samples[offset:offset+480], sample_pos=start,
                    epoch_id='bench', received_monotonic=start/48000)))
                gain_samples.append(dict(time_s=start/48000,
                    duration_s=len(frame.samples[offset:offset+480])/48000,
                    gain=pipeline._beat_fusion.trigger.primary.gain,
                    tempo_bpm=pipeline._beat_fusion.clock.tempo_bpm,
                    locked=pipeline._beat_fusion.clock.locked))

    try:
        for pos in range(0, len(pcm), rate//100):
            samples = pcm[pos:pos+rate//100]
            feed(canonicalizer.push(DataResult(DecodedSourceFrame(
                samples, rate, pcm.shape[1], 'offline', pos,
                bool(np.any(np.abs(samples) >= 1)), round(pos/rate*1e9)))))
        feed(canonicalizer.push(EndOfStream()))
        consume(pipeline.end_of_stream())
    finally:
        pipeline.stop()
    duration = len(pcm)/rate
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
        '-show_entries', 'stream=codec_name,sample_rate,channels:format=duration',
        '-of', 'json', str(path)], text=True))
    summary = dict(relative_gate=dict(k=k, window_s=window_s, refractory_ms=refractory_ms,
        full_k=full_k, absolute_min=profile.onset_delta_abs), input=str(path.resolve()),
        input_sha256=hashlib.sha256(
        path.read_bytes()).hexdigest(), source_probe=probe, format=fmt, duration_s=duration,
                   agc_max_gain=profile.agc_max_gain, maximum_observed_gain=maximum_gain,
                   tracker_gain_floor=profile.tracker_gain_floor, modes={})
    gains = np.array([r['gain'] for r in gain_samples])
    weights = np.array([r['duration_s'] for r in gain_samples])
    order = np.argsort(gains)
    cumulative = np.cumsum(weights[order])/sum(weights)
    summary['gain_over_time'] = dict(
        median=float(gains[order[np.searchsorted(cumulative, .5)]]),
        p90=float(gains[order[np.searchsorted(cumulative, .9)]]),
        time_at_ceiling_s=sum(r['duration_s'] for r in gain_samples
                              if r['gain'] >= profile.agc_max_gain-1e-9),
        time_above_8_s=sum(r['duration_s'] for r in gain_samples if r['gain'] > 8.),
        samples=len(gain_samples))
    summary['gain_over_time']['time_above_8_percent'] = (
        100*summary['gain_over_time']['time_above_8_s']/duration)
    summary['gain_over_time']['time_at_ceiling_percent'] = (
        100*summary['gain_over_time']['time_at_ceiling_s']/duration)
    summary['strengths'] = {}
    for label, items in [('raw_detector', raw_events), ('onset_accents', accepted_events),
                         ('tracker_accents', [dict(strength=e.strength, strength_raw=e.strength_raw)
                                              for e in selected['tracker']])]:
        summary['strengths'][label] = {field: distribution([r[field] for r in items])
                                      for field in ('strength', 'strength_raw')}
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in [('gain-over-time', gain_samples), ('raw-onsets', raw_events),
                       ('accepted-onsets', accepted_events), ('raw-envelope', raw_frames)]:
        with (out/f'{name}.csv').open('w') as stream:
            writer = csv.DictWriter(stream, list(rows[0]) if rows else ['time_s'])
            writer.writeheader()
            writer.writerows(rows)
    if estimate_tempo:
        import librosa
        mono = np.mean(pcm, axis=1)
        estimates = {}
        for prior in (120., 72.):
            tempo, beats = librosa.beat.beat_track(y=mono, sr=rate, start_bpm=prior)
            bpm = float(np.asarray(tempo).reshape(-1)[0])
            estimates[str(prior)] = dict(start_bpm=prior, tempo_bpm=bpm,
                                         beats_per_s=bpm/60, detected_beats=len(beats),
                                         beat_times_s=librosa.frames_to_time(
                                             beats, sr=rate).tolist())
        summary['librosa'] = dict(version=librosa.__version__, estimates=estimates,
            reference='72.0', note='72 BPM prior supplied by owner; default prior also reported')
    reference_times = None
    if reference:
        with reference.open() as stream:
            reference_times = [float(row['time_s']) for row in csv.DictReader(stream)]
    for mode, events in selected.items():
        destination = out/mode
        destination.mkdir(parents=True, exist_ok=True)
        # Existing A/B reference scorer compares LMS/AirPlay columns. These are
        # identical offline copies, not claims about either live route.
        rows = [dict(audible_t=e.candidate_sample/48000, strength=e.strength,
                     source='tempo_clock' if e.predicted else 'detector') for e in events]
        for label in ('lms', 'airplay'):
            with (destination/f'{label}-beats.csv').open('w') as stream:
                writer = csv.DictWriter(stream, ['audible_t', 'strength', 'source'])
                writer.writeheader()
                writer.writerows(rows)
        summary['modes'][mode] = dict(accents=len(events), accents_per_s=len(events)/duration,
            accents_per_minute=60*len(events)/duration,
            predicted=sum(e.predicted for e in events),
            break_accents=([sum(a <= e.candidate_sample/48000 < b for e in events)
                            for a, b in BREAKS] if duration >= 272 else None))
        if reference_times is not None:
            summary['modes'][mode]['non_break_hits'] = {
                str(tolerance): reference_hits(events, reference_times, duration, tolerance)
                for tolerance in (.01, .05)}
        spec = importlib.util.spec_from_file_location('ab_tools', Path(__file__).with_name(
            'ab-tools.py'))
        ab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ab)
        if reference:
            os.environ['AB_REFERENCE_BEATS'] = str(reference)
        ab.write_analysis(destination, path)
    summary['background_spread'] = reference_trace(raw_frames, out, window_s)
    add_coincidence(summary, selected)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


def add_coincidence(summary, selected):
    estimates = summary.get('librosa', {}).get('estimates', {})
    beats = estimates.get('120.0', {}).get('beat_times_s')
    if beats is None:
        return
    for mode, events in selected.items():
        coincident = 0
        for event in events:
            stamp = event.candidate_sample/48000
            index = bisect.bisect_left(beats, stamp-.07)
            coincident += index < len(beats) and beats[index] <= stamp+.07+1e-9
        summary['modes'][mode]['librosa_coincidence'] = dict(
            coincident=coincident, fired=len(events), tolerance_s=.07,
            ratio=coincident/len(events) if events else None)


def cached_gate(source, out, reference, *, k, refractory_ms, window_s=3., full_k=None):
    """Replay immutable detector candidates through the production lighting gate."""
    full_k = k+1 if full_k is None else full_k
    summary = json.loads((source/'summary.json').read_text())
    summary['candidate_cache'] = str(source.resolve())
    minimum = summary['relative_gate']['absolute_min']
    summary['relative_gate'] = dict(k=k, window_s=window_s, refractory_ms=refractory_ms,
                                    full_k=full_k, absolute_min=minimum)
    gate = RelativeOnsetGate(k, window_s, refractory_ms, full_k, minimum)
    events, actions = [], []
    with (source/'raw-envelope.csv').open() as stream:
        for row in csv.DictReader(stream):
            frame = OnsetEnvelopeFrame(int(row['sample_pos']), **{
                band: float(row[band]) if row[band] else None
                for band in ('full','bass','mid','treble')})
            actions.append((frame.sample_pos, 0, row['epoch'], frame))
    with (source/'raw-onsets.csv').open() as stream:
        for row in csv.DictReader(stream):
            event = SimpleNamespace(id=tuple(json.loads(row['event_id'])), epoch=row['epoch'],
                candidate_sample=round(float(row['time_s'])*48000), predicted=False,
                bands=frozenset(row['bands'].split(',')), strength_raw=float(row['strength_raw']),
                strength=float(row['strength']))
            actions.append((event.candidate_sample, 1, float(row['bass_strength']), event))
    for _, kind, data, item in sorted(actions, key=lambda row: row[:2]):
        if kind == 0:
            gate.observe(data, item)
        elif gate.accepts(item, data):
            events.append(item)
    mode = dict(accents=len(events), accents_per_s=len(events)/summary['duration_s'],
                accents_per_minute=60*len(events)/summary['duration_s'],
                predicted=0, break_accents=([sum(a <= e.candidate_sample/48000 < b for e in events)
                                           for a,b in BREAKS]
                                          if summary['duration_s'] >= 272 else None))
    if reference:
        with reference.open() as stream:
            refs = [float(row['time_s']) for row in csv.DictReader(stream)]
        mode['non_break_hits'] = {str(t): reference_hits(events, refs, summary['duration_s'],t)
                                  for t in (.01,.05)}
    summary['modes']['onset'] = mode
    summary['strengths']['onset_accents'] = {field: distribution(
        [getattr(event, field) for event in events]) for field in ('strength','strength_raw')}
    add_coincidence(summary, {'onset':events})
    out.mkdir(parents=True, exist_ok=True)
    with (out/'accepted-onsets.csv').open('w') as stream:
        writer = csv.DictWriter(stream,['time_s','strength_raw'])
        writer.writeheader()
        writer.writerows(dict(time_s=e.candidate_sample/48000, strength_raw=e.strength_raw)
                         for e in events)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def reference_trace(rows, out, window_s):
    """Every-frame median/MAD traces in the same raw units as candidate strength."""
    gate = RelativeOnsetGate(window_s=window_s)
    traces = []
    for row in sorted(rows, key=lambda row: row['sample_pos']):
        frame = OnsetEnvelopeFrame(row['sample_pos'], **{
            band: row[band] for band in ('full','bass','mid','treble')})
        gate.observe(row['epoch'], frame)
        trace = dict(time_s=frame.sample_pos/48000)
        for band in ('full','bass','mid','treble'):
            ref = gate.reference(trace['time_s'],band)
            if ref is not None:
                trace[band+'_background'], trace[band+'_spread'] = ref
        traces.append(trace)
    fields = ['time_s']+[band+suffix for band in ('full','bass','mid','treble')
                          for suffix in ('_background','_spread')]
    with (out/'background-spread.csv').open('w') as stream:
        writer = csv.DictWriter(stream,fields)
        writer.writeheader()
        writer.writerows(traces)
    return {field: distribution([row[field] for row in traces if field in row])
            for field in fields[1:]}


def reference_hits(events, references, duration, tolerance):
    """Reference-beat recall outside the four specified half-open break windows.

    A reference beat is hit once if any non-break accent is within the fixed
    tolerance. Repeated accents cannot increase recall beyond one hit per beat.
    """
    def outside_breaks(t):
        return not any(start <= t < end for start, end in BREAKS)

    times = sorted(event.candidate_sample/48000 for event in events
                   if outside_breaks(event.candidate_sample/48000))
    references = [t for t in references if 0 <= t < duration and outside_breaks(t)]
    hits = 0
    for stamp in references:
        index = bisect.bisect_left(times, stamp-tolerance)
        hits += index < len(times) and times[index] <= stamp+tolerance+1e-9
    return dict(hits=hits, reference_beats=len(references), tolerance_s=tolerance,
                hit_rate=hits/len(references) if references else None,
                sections='complement of the four specified break windows')


def distribution(values):
    if not values:
        return dict(count=0)
    return dict(count=len(values), minimum=float(np.min(values)),
                median=float(np.median(values)), p90=float(np.percentile(values, 90)),
                p99=float(np.percentile(values, 99)), maximum=float(np.max(values)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--ceiling', type=float, default=64.)
    parser.add_argument('--floor', type=float, default=.3)
    parser.add_argument('--estimate-tempo', action='store_true')
    parser.add_argument('--relative-k', type=float, default=2.)
    parser.add_argument('--window-s', type=float, default=3.)
    parser.add_argument('--refractory-ms', type=float, default=120.)
    parser.add_argument('--full-k', type=float)
    parser.add_argument('--candidate-cache', type=Path)
    args = parser.parse_args()
    if args.candidate_cache:
        print(json.dumps(cached_gate(args.candidate_cache, args.out, args.reference,
            k=args.relative_k, refractory_ms=args.refractory_ms, window_s=args.window_s,
            full_k=args.full_k), indent=2))
    else:
        bench(args.input, args.out, args.reference, ceiling=args.ceiling, floor=args.floor,
              estimate_tempo=args.estimate_tempo, k=args.relative_k, window_s=args.window_s,
              refractory_ms=args.refractory_ms, full_k=args.full_k)


if __name__ == '__main__':
    main()
