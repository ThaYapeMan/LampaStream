"""Whole-file analysis, independent of transports, players and lamp outputs.

librosa uses start_bpm=120 and tightness=100. Low-band attack energy is
positive RMS rise in 5 ms windows after a 40–150 Hz fourth-order bandpass.
The kick threshold is 15% of the track's 90th-percentile attack peak.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess

import librosa
import numpy as np
import soundfile as sf
import soxr
from scipy.ndimage import gaussian_filter1d
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
    values = [float(np.max(energy[max(0, round((b-.07)/step)):
                                 min(len(energy), round((b+.07)/step)+1)])) for b in beats]
    flags = np.asarray(values) >= threshold
    confidence = float(np.clip(.5*np.mean(flags)+.5*(1-min(
        1., float(np.std(np.diff(beats)))/float(np.mean(np.diff(beats))))), 0, 1))
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr,
                     float(np.clip(tempo, 60, 180)), tuple(map(float, beats)),
                     tuple(map(bool, flags)), sections_for(beats, flags, duration), confidence,
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


def analyse(raw: bytes) -> TrackGrid:
    y, sr, lossless = decode(raw)
    duration = len(y) / sr
    if duration < 2 or not np.isfinite(y).all():
        raise ValueError('Audio must contain at least two seconds of finite samples')
    energy, hop, threshold = low_band_attacks(y, sr)
    n = len(energy)
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
            # Preserve expressive timing. Only a demonstrably rigid track is fitted.
            regularity = np.std(np.diff(observed))/np.mean(np.diff(observed))
            if regularity < .04:
                indices = np.arange(len(observed))
                step = max(2, len(observed)//8)
                slope = float(np.median((observed[step:]-observed[:-step])/step))
                phase = float(np.median(observed-indices*slope))
                for _ in range(3):
                    good_fit = abs(observed-(phase+indices*slope)) < .05
                    slope, phase = np.polyfit(indices[good_fit], observed[good_fit], 1)
                period = float(slope)
                beats = observed.copy()
            else:
                beats = observed.copy()
            offsets = []
            values = []
            for beat in beats:
                lo, hi = max(0, round((beat-.07)*sr/hop)), min(n, round((beat+.07)*sr/hop)+1)
                index = lo+int(np.argmax(energy[lo:hi]))
                offsets.append(index*hop/sr-beat)
                values.append(energy[index])
            phase_shift = float(np.median(offsets))
            beats = beats+phase_shift
            lag = round(period*sr/hop)
            rhythm = float(np.max(autocorrelation[max(1, lag-3):lag+4]))
            score = float(np.mean(values)*rhythm)
            # Median inter-beat interval over the entire attack-refined file,
            # rather than the quantised median of 512-sample beat hops.
            attack_intervals = np.diff(observed+np.asarray(offsets))
            refined_tempo = 60/float(np.median(attack_intervals))
            scored.append((score, refined_tempo, beats))
    best = max(s[0] for s in scored)
    _, tempo, beats = min((s for s in scored if s[0] >= best*(1-1e-6)), key=lambda s: s[1])
    beats = beats[(beats >= 0) & (beats < duration)]
    values = []
    for beat in beats:
        lo, hi = max(0, round((beat-.07)*sr/hop)), min(n, round((beat+.07)*sr/hop)+1)
        values.append(float(np.max(energy[lo:hi])))
    flags = np.asarray(values) >= threshold
    good = flags
    regularity = 1 - min(1., float(np.std(np.diff(tracked)))/float(np.mean(np.diff(tracked))))
    confidence = float(np.clip(.5*regularity + .5*np.mean(good), 0, 1))
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr, float(tempo),
                     tuple(map(float, beats)), tuple(map(bool, flags)),
                     sections_for(beats, flags, duration), confidence,
                     'content-v1' if lossless else 'unknown')


if __name__ == '__main__':
    import sys
    from pathlib import Path
    function = analyse_head if "--head" in sys.argv[2:] else analyse
    print(json.dumps(function(Path(sys.argv[1]).read_bytes()).to_dict(), allow_nan=False))
