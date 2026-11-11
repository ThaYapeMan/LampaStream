"""Whole-file analysis, independent of transports, players and lamp outputs.

librosa uses start_bpm=120 and tightness=100. Low-band attack energy is
positive RMS rise in 5 ms windows after a 40–150 Hz fourth-order bandpass.
Rigid tempo sections share a fitted lattice and persistent kick decisions.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
from itertools import groupby

import librosa
import numpy as np
import soundfile as sf
import soxr
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import butter, correlate, find_peaks, sosfilt, stft

from . import VERSION, Section, TrackGrid


def decode(raw: bytes):
    try:
        audio, rate = sf.read(io.BytesIO(raw), dtype='float32', always_2d=True)
        # libsndfile cannot decode ALAC in M4A; use the existing FFmpeg tooling.
        info = sf.info(io.BytesIO(raw))
        lossless = info.subtype not in ('MPEG_LAYER_III', 'VORBIS', 'OPUS')
        return audio.mean(axis=1), rate, lossless
    except sf.LibsndfileError:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json',
                                'pipe:0'], input=raw, capture_output=True, check=True, timeout=30)
        stream = next(s for s in json.loads(probe.stdout)['streams'] if s['codec_type'] == 'audio')
        rate = int(stream['sample_rate'])
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-f', 'f32le',
                                 '-ac', '1', '-ar', str(rate), 'pipe:1'], input=raw,
                                capture_output=True, check=True, timeout=120)
        return np.frombuffer(result.stdout, '<f4'), rate, (
            stream['codec_name'] in ('alac', 'flac') or stream['codec_name'].startswith('pcm_'))


def decode_head(raw, seconds=60):
    """Decode bounded content from an original prefix, tolerating a final partial FLAC frame."""
    try:
        with sf.SoundFile(io.BytesIO(raw)) as stream:
            rate = stream.samplerate
            chunks = []
            remaining = round(rate*seconds)
            while remaining:
                try:
                    chunk = stream.read(min(16384, remaining), dtype='float32', always_2d=True)
                except sf.LibsndfileError:
                    break
                if not len(chunk):
                    break
                chunks.append(chunk.mean(axis=1))
                remaining -= len(chunk)
            if not chunks or sum(map(len, chunks)) < 2*rate:
                raise ValueError('Insufficient decodable head audio')
            return np.concatenate(chunks), rate, stream.subtype not in (
                'MPEG_LAYER_III', 'VORBIS', 'OPUS')
    except sf.LibsndfileError:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json',
                                'pipe:0'], input=raw, capture_output=True, check=True, timeout=10)
        stream = next(s for s in json.loads(probe.stdout)['streams'] if s['codec_type'] == 'audio')
        rate = int(stream['sample_rate'])
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-t', str(seconds),
                                 '-f', 'f32le', '-ac', '1', '-ar', str(rate), 'pipe:1'],
                                input=raw, capture_output=True, check=True, timeout=20)
        return np.frombuffer(result.stdout, '<f4'), rate, (
            stream['codec_name'] in ('alac', 'flac') or stream['codec_name'].startswith('pcm_'))


def analyse_head(raw, seconds=60):
    """Provisional spectral-onset DP grid without whole-file JIT warm-up.

    A 64-band log-mel flux at 11025 Hz supplies candidate periods. Dynamic
    programming scores their local beat paths; low-band energy and periodicity
    choose the path. The full analyser remains authoritative.
    """
    y, sr, lossless = decode_head(raw, seconds)
    if len(y) < 2*sr or not np.isfinite(y).all():
        raise ValueError('Insufficient finite head audio')
    duration = len(y)/sr
    energy, hop, threshold = low_band_attacks(y, sr)
    step = hop/sr
    mono = soxr.resample(y, sr, 11025)
    _, _, spectrum = stft(mono, fs=11025, nperseg=1024, noverlap=896)
    frequencies = np.linspace(0, 5512.5, 513)
    edges = 700*(10**(np.linspace(0, 2595*np.log10(1+5512.5/700), 66)/2595)-1)
    weights = np.maximum(0, np.minimum(
        (frequencies[None, :]-edges[:-2, None])/(edges[1:-1, None]-edges[:-2, None]),
        (edges[2:, None]-frequencies[None, :])/(edges[2:, None]-edges[1:-1, None])))
    power = weights @ abs(spectrum)**2
    decibels = 10*np.log10(np.maximum(1e-12, power))
    onset = np.maximum(0, np.diff(decibels, axis=1)).mean(axis=0)
    autocorr = correlate(onset, onset, method='fft')[len(onset)-1:]
    odf_step = 128/11025
    low, high = round(60/180/odf_step), min(len(autocorr)-1, round(60/60/odf_step))
    peaks, _ = find_peaks(autocorr[low:high+1])
    lags = sorted(peaks+low, key=lambda lag: autocorr[lag], reverse=True)[:8]
    if not lags:
        raise ValueError('No head tempo in prior')
    candidates = []
    normalized = onset/max(1e-9, float(np.std(onset)))
    for lag in lags:
        sigma = max(1., lag/32)
        local = gaussian_filter1d(normalized, sigma)*sigma
        offsets = np.arange(max(1, round(lag/2)), round(2*lag)+1)
        penalties = -100*np.log(offsets/lag)**2
        cumulative = np.zeros(len(local))
        previous = np.full(len(local), -1, dtype=int)
        for i in range(len(local)):
            allowed = offsets <= i
            if np.any(allowed):
                ancestors = i-offsets[allowed]
                scores = cumulative[ancestors]+penalties[allowed]
                winner = int(np.argmax(scores))
                if scores[winner] > 0:
                    cumulative[i] = scores[winner]
                    previous[i] = ancestors[winner]
            cumulative[i] += local[i]
        end = max(0, len(local)-2*lag)
        index = end+int(np.argmax(cumulative[end:]))
        indices = []
        while index >= 0:
            indices.append(index)
            index = int(previous[index])
        beats = (np.asarray(indices[::-1])+1)*odf_step
        beats = beats[beats < duration]
        if len(beats) < 3:
            continue
        offsets = []
        values = []
        for beat in beats:
            lo, hi = max(0, round((beat-.07)/step)), min(len(energy), round((beat+.07)/step)+1)
            peak = lo+int(np.argmax(energy[lo:hi]))
            offsets.append(peak*step-beat)
            values.append(float(energy[peak]))
        score = float(autocorr[lag]*np.mean(values)*np.sqrt(len(beats)))
        tempo = 60/float(np.median(np.diff(beats+np.asarray(offsets))))
        beats = beats+float(np.median(offsets))
        candidates.append((score, tempo, beats))
    if not candidates:
        raise ValueError('No supported head beat path')
    best_score = max(c[0] for c in candidates)
    _, tempo, beats = min((c for c in candidates if c[0] >= best_score*(1-1e-6)),
                          key=lambda c: c[1])
    beats = beats[(beats >= 0) & (beats < duration)]
    beats, flags, tempo, tempo_sections = fit_sections(beats, energy, step, duration)
    confidence = float(np.clip(.5*np.mean(flags)+.5*(1-min(
        1., float(np.std(np.diff(beats)))/float(np.mean(np.diff(beats))))), 0, 1))
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr,
                     float(np.clip(tempo, 60, 180)), tuple(map(float, beats)),
                     tuple(map(bool, flags)),
                     sections_for(beats, flags, duration)+tempo_sections, confidence,
                     'content-v1' if lossless else 'unknown', provisional=True)


def sections_for(beats, flags, duration):
    sections = []
    start = None
    for i in range(len(flags) + 1):
        if i < len(flags) and not flags[i]:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= 2:
                end = float(beats[i]) if i < len(beats) else duration
                sections.append(Section('break', float(beats[start]), end))
                if i < len(beats):
                    sections.append(Section('drop', end, end))
            start = None
    return tuple(sections)


def low_band_attacks(y, sr):
    hop = max(1, round(sr * .005))
    low = sosfilt(butter(4, [40, 150], btype='bandpass', fs=sr, output='sos'), y)
    n = len(low) // hop
    rms = np.sqrt(np.mean(low[:n*hop].reshape(n, hop)**2, axis=1))
    energy = np.maximum(0, np.diff(rms, prepend=0))
    peaks, _ = find_peaks(energy, distance=round(.16*sr/hop),
                          prominence=max(1e-9, float(np.max(energy))*.015))
    if not len(peaks):
        raise ValueError('No low-band attacks found')
    strengths = energy[peaks]
    threshold = float(np.percentile(strengths, 90)) * .15
    return energy, hop, threshold


def attack_values(beats, energy, step, radius=.07):
    values, offsets = [], []
    for beat in beats:
        lo = max(0, min(len(energy)-1, round((beat-radius)/step)))
        hi = max(lo+1, min(len(energy), round((beat+radius)/step)+1))
        peak = lo+int(np.argmax(energy[lo:hi]))
        values.append(energy[peak])
        offsets.append(peak*step-beat)
    return np.asarray(values), np.asarray(offsets)


def kick_runs(beats, energy, step, period):
    return kick_evidence(beats, energy, step, period)[0]


def kick_evidence(beats, energy, step, period):
    """Hysteretic marginal evidence with immediate, coherent strong evidence."""
    on, offsets = attack_values(beats, energy, step)
    # A bassline-only phase has scattered peak offsets. Do not claim kick
    # support without a coherent section, especially in a provisional head.
    if np.median(abs(offsets-np.median(offsets))) > .02:
        empty = np.zeros(len(beats), dtype=bool)
        return empty, empty.copy(), np.zeros(len(beats))
    off, _ = attack_values(beats+period/2, energy, step)
    # Normalise contrast to this tempo section: off-beat bass can be louder
    # than a kick, so a universal absolute ratio is not reliable.
    reference = float(np.median(on))/max(1e-12, float(np.median(off)))
    window_on = median_filter(on, size=9, mode='nearest')
    window_off = median_filter(off, size=9, mode='nearest')
    level = np.percentile(on, 90)*max(.02, .22/max(1., reference))
    decisions = (window_on >= .4*reference*np.maximum(1e-12, window_off)) & (
        window_on >= max(1e-12, level))
    # A four-beat silence must not disappear under a nine-beat median.
    silent = median_filter(on, size=3, mode='nearest') < level
    decisions[silent] = False
    flags = np.zeros(len(beats), dtype=bool)
    state, pending = False, 0
    for i, decision in enumerate(decisions):
        pending = pending+1 if decision != state else 0
        if pending >= 4:
            state = bool(decision)
            flags[i-3:i+1] = state
            pending = 0
        flags[i] = state
    supported = np.flatnonzero(flags)
    if not len(supported):
        return flags, np.zeros(len(beats), dtype=bool), np.zeros(len(beats))
    # Kick-bearing runs establish level anchors. A local median can follow
    # substantial volume changes inside a run without borrowing the body level
    # for a quiet intro/outro.
    spans = []
    start = 0
    anchors = np.zeros(len(beats))
    for state, group in groupby(flags):
        end = start+len(list(group))
        spans.append((state, start, end))
        if state:
            anchors[start:end] = np.median(on[start:end])
        start = end
    section_level = np.interp(np.arange(len(beats)), supported, anchors[supported])
    local = median_filter(on[supported], size=17, mode='nearest')
    baseline = anchors[supported]
    adjusted = np.where((local < baseline/1.5) | (local > baseline*1.5), local, baseline)
    kick_level = np.interp(np.arange(len(beats)), supported, adjusted)
    isolated = np.zeros(len(beats), dtype=bool)
    for state, start, end in spans:
        if state or start == 0:
            continue
        # Resolve isolated attacks within breaks as their own level sections.
        # Short breaks retain a level anchor on both sides. Long breaks require
        # an eightfold rise above their own background instead.
        if end-start <= 16:
            candidates = on[start:end] >= .28*section_level[start:end]
        else:
            candidates = on[start:end] > 8*max(1e-12, float(np.median(on[start:end])))
        index = start
        for present, group in groupby(candidates):
            stop = index+len(list(group))
            if present:
                kick_level[index:stop] = np.median(on[index:stop])
                isolated[index:stop] = True
            index = stop
    # A strong attack must be phase-coherent, or belong to an isolated attack
    # section; a nearby bass note alone is insufficient strong evidence.
    strong_on = (on >= kick_level) & ((abs(offsets) <= .012) | isolated)
    strong_off = on <= .25*kick_level
    ambiguous = ~(strong_on | strong_off)
    flags[strong_on] = True
    flags[strong_off] = False
    # Strong exceptions may split a marginal run into short fragments. Merge
    # only fragments containing no strong evidence; never erase an exception.
    while True:
        start = 0
        for _, group in groupby(flags):
            end = start+len(list(group))
            if end-start < 4 and np.all(ambiguous[start:end]):
                flags[start:end] = flags[start-1] if start else flags[end]
                break
            start = end
        else:
            break
    return flags, ambiguous, kick_level


def tempo_boundaries(observed):
    # Eight-beat slopes suppress the 512-sample tracker hop quantisation.
    if len(observed) < 25:
        return [0, len(observed)]
    slopes = (observed[8:]-observed[:-8])/8
    boundaries = [0]
    baseline = float(np.median(slopes[:16]))
    i = 8
    while i < len(slopes)-16:
        following = slopes[i:i+16]
        candidate = float(np.median(following))
        if (abs(candidate/baseline-1) > .02
                and np.all(abs(following/baseline-1) > .02)
                and np.std(following)/candidate < .01):
            boundaries.append(i+4)
            baseline = candidate
            i += 16
        else:
            i += 1
    refined = [0]
    for boundary in boundaries[1:]:
        lo, hi = max(refined[-1]+8, boundary-12), min(len(observed)-8, boundary+13)
        def cost(split):
            total = 0.
            for part in (observed[max(refined[-1], split-32):split],
                         observed[split:min(len(observed), split+32)]):
                x = np.arange(len(part))
                slope, phase = np.polyfit(x, part, 1)
                total += float(np.mean(np.minimum((part-phase-x*slope)**2, .05**2)))
            return total
        refined.append(min(range(lo, hi), key=cost))
    return refined+[len(observed)]


def fit_sections(observed, energy, step, duration):
    """Fit rigid sections, preserving expressive tracker positions verbatim."""
    result, flags, sections, choices = [], [], [], []
    boundaries = tempo_boundaries(observed)
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        positions = observed[start:end].copy()
        if len(positions) < 3:
            continue
        intervals = np.diff(positions)
        period = float(np.median(intervals))
        rigid = np.std(intervals)/np.mean(intervals) < .04-1e-9
        if rigid:
            indices = np.arange(len(positions))
            stride = max(2, len(positions)//8)
            period = float(np.median((positions[stride:]-positions[:-stride])/stride))
            phase = float(np.median(positions-indices*period))
            # Reassign lattice indices so a DP insertion/deletion cannot bend
            # an otherwise rigid section. Strong attacks determine the slope.
            values, offsets = attack_values(positions, energy, step)
            supported = values >= np.percentile(values, 90)*.5
            attacks = positions+offsets
            for _ in range(6):
                indices = np.rint((attacks-phase)/period)
                good = supported & (abs(attacks-(phase+indices*period)) < .07)
                if np.count_nonzero(good) < 3:
                    break
                period, phase = map(float, np.polyfit(indices[good], attacks[good], 1))
            lower = 0 if start == 0 else (observed[start-1]+observed[start])/2
            upper = duration if end == len(observed) else (observed[end-1]+observed[end])/2
            indices = np.arange(np.ceil((lower-phase)/period), np.ceil((upper-phase)/period))
            positions = phase+indices*period
            kick = kick_runs(positions, energy, step, period)
            _, offsets = attack_values(positions, energy, step)
            if np.any(kick):
                positions += float(np.median(offsets[kick]))
        kick = kick_runs(positions, energy, step, period)
        valid = (positions >= 0) & (positions < duration)
        positions, kick = positions[valid], kick[valid]
        result.extend(positions)
        flags.extend(kick)
        tempo = 60/period
        sections.append(Section('tempo', float(positions[0]),
                                float((observed[end-1]+observed[end])/2)
                                if end < len(observed) else duration, tempo))
        choices.append((np.count_nonzero(kick)*period, len(positions)*period, tempo))
    return np.asarray(result), np.asarray(flags), max(choices)[2], tuple(sections)


def analyse(raw: bytes) -> TrackGrid:
    y, sr, lossless = decode(raw)
    duration = len(y) / sr
    if duration < 2 or not np.isfinite(y).all():
        raise ValueError('Audio must contain at least two seconds of finite samples')
    energy, hop, threshold = low_band_attacks(y, sr)
    _, tracked = librosa.beat.beat_track(y=y, sr=sr, hop_length=512,
                                         start_bpm=120, tightness=100, units='time', trim=False)
    if len(tracked) < 3:
        raise ValueError('Insufficient beats')
    tempo = 60 / float(np.median(np.diff(tracked)))
    candidates = sorted({tempo * scale for scale in (.5, 1, 2) if 60 <= tempo*scale <= 180})
    if not candidates:
        raise ValueError('No tempo in 60–180 BPM range')
    autocorrelation = correlate(energy, energy, method="fft")[len(energy)-1:]
    scored = []
    base_period = float(np.median(np.diff(tracked)))
    for bpm in candidates:
        period = 60 / bpm
        ratio = period/base_period
        if ratio > 1.5:
            variants = [tracked[::2], tracked[1::2]]
        elif ratio < .75:
            variants = [np.sort(np.concatenate((tracked, (tracked[:-1]+tracked[1:])/2)))]
        else:
            variants = [tracked]
        for observed in variants:
            beats, flags, refined_tempo, tempo_sections = fit_sections(
                observed, energy, hop/sr, duration)
            values, _ = attack_values(beats, energy, hop/sr)
            lag = round(period*sr/hop)
            rhythm = float(np.max(autocorrelation[max(1, lag-3):lag+4]))
            score = float(np.mean(values)*rhythm)
            scored.append((score, refined_tempo, beats, flags, tempo_sections))
    best = max(s[0] for s in scored)
    _, tempo, beats, flags, tempo_sections = min(
        (s for s in scored if s[0] >= best*(1-1e-6)), key=lambda s: s[1])
    good = flags
    regularity = 1 - min(1., float(np.std(np.diff(tracked)))/float(np.mean(np.diff(tracked))))
    confidence = float(np.clip(.5*regularity + .5*np.mean(good), 0, 1))
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr, float(tempo),
                     tuple(map(float, beats)), tuple(map(bool, flags)),
                     sections_for(beats, flags, duration)+tempo_sections, confidence,
                     'content-v1' if lossless else 'unknown')


if __name__ == '__main__':
    import sys
    from pathlib import Path
    function = analyse_head if "--head" in sys.argv[2:] else analyse
    print(json.dumps(function(Path(sys.argv[1]).read_bytes()).to_dict(), allow_nan=False))
