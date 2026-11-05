#!/usr/bin/env python3
"""Offline LIGHTS-01 stream evidence using production DSP and the A/B scorer."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from replay_chain import decode  # noqa: E402

from lampastream.beat_accents import select_events  # noqa: E402
from lampastream.canonicalizer import (  # noqa: E402
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    DecodedSourceFrame,
    EndOfStream,
)
from lampastream.models import Profile  # noqa: E402
from lampastream.player_manager import _make_canonical_pipeline  # noqa: E402

BREAKS = [(210, 212), (240, 242), (261, 262), (270, 272)]


def bench(path, out, reference=None, *, ceiling=64., floor=.3, estimate_tempo=False):
    pcm, rate, fmt = decode(path)
    profile = Profile(agc_max_gain=ceiling, onset_gain_floor=floor)
    pipeline = _make_canonical_pipeline(None, profile)
    pipeline._beat_fusion.gain_settings = profile.agc_max_gain, profile.onset_gain_floor
    canonicalizer = AudioCanonicalizer()
    selected = {mode: [] for mode in ('onset', 'tracker')}
    maximum_gain = 0.
    gain_samples, raw_events, accepted_events = [], [], []

    def consume(records):
        nonlocal maximum_gain
        for record in records:
            maximum_gain = max(maximum_gain, record.features.agc_gain)
        for record in records:
            raw_events.extend(dict(time_s=e.candidate_sample/48000,
                strength=e.strength, strength_raw=e.strength_raw, gain=record.features.agc_gain)
                for e in record.features.diagnostic_events)
        for mode in selected:
            events = select_events(mode, [e for r in records for e in r.features.onset_events],
                                   records, profile.agc_max_gain, profile.onset_gain_floor)
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
    summary = dict(input=str(path.resolve()), input_sha256=hashlib.sha256(
        path.read_bytes()).hexdigest(), source_probe=probe, format=fmt, duration_s=duration,
                   agc_max_gain=profile.agc_max_gain, maximum_observed_gain=maximum_gain,
                   onset_gain_floor=profile.onset_gain_floor, modes={})
    gains = np.array([r['gain'] for r in gain_samples])
    weights = np.array([r['duration_s'] for r in gain_samples])
    order = np.argsort(gains)
    cumulative = np.cumsum(weights[order])/sum(weights)
    summary['gain_over_time'] = dict(
        median=float(gains[order[np.searchsorted(cumulative, .5)]]),
        p90=float(gains[order[np.searchsorted(cumulative, .9)]]),
        time_at_ceiling_s=sum(r['duration_s'] for r in gain_samples
                              if r['gain'] >= profile.agc_max_gain-1e-9),
        samples=len(gain_samples))
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
                       ('accepted-onsets', accepted_events)]:
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
                                         beats_per_s=bpm/60, detected_beats=len(beats))
        summary['librosa'] = dict(version=librosa.__version__, estimates=estimates,
            reference='72.0', note='72 BPM prior supplied by owner; default prior also reported')
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
        spec = importlib.util.spec_from_file_location('ab_tools', Path(__file__).with_name(
            'ab-tools.py'))
        ab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ab)
        if reference:
            os.environ['AB_REFERENCE_BEATS'] = str(reference)
        ab.write_analysis(destination, path)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


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
    args = parser.parse_args()
    bench(args.input, args.out, args.reference, ceiling=args.ceiling, floor=args.floor,
          estimate_tempo=args.estimate_tempo)


if __name__ == '__main__':
    main()
