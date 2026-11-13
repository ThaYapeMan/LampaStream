"""Whole-file analysis, independent of transports, players and lamp outputs.

librosa uses start_bpm=120 and tightness=100. Low-band attack energy is
positive RMS rise in 5 ms windows after a 40–150 Hz fourth-order bandpass.
Rigid tempo sections share a fitted lattice and persistent bass drum decisions.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
from contextlib import contextmanager
from itertools import groupby

# The CLI owns a dedicated worker; ordinary API imports must not alter callers.
if __name__ == '__main__':
    import os

    from .worker import worker_environment

    os.environ.update(worker_environment())

import librosa
import numpy as np
import soundfile as sf
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import correlate, find_peaks, stft

from ..attacks import attack_envelope
from ..canonicalizer import (
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    DecodedSourceFrame,
    EndOfStream,
)
from . import VERSION, Section, TrackGrid
from .fingerprint import fingerprint
from .rhythm import describe


class BufferReader(io.RawIOBase):
    """Seekable view of original bytes/mmap without BytesIO's whole-file copy."""
    def __init__(self, raw):
        self.raw = raw
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset+(0 if whence == 0 else self.position if whence == 1 else len(self.raw))
        if position < 0:
            raise ValueError('Negative seek')
        self.position = position
        return position

    def read(self, size=-1):
        end = len(self.raw) if size < 0 else min(len(self.raw), self.position+size)
        result = self.raw[self.position:end]
        self.position = end
        return result

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


@contextmanager
def decoded_stream(raw, seconds=None):
    """Open native PCM without retaining a whole decoded file or pipe output."""
    try:
        stream = sf.SoundFile(BufferReader(raw))
    except sf.LibsndfileError:
        # A regular input also supports M4A containers with a trailing moov atom.
        with tempfile.TemporaryDirectory(prefix='grid-decode-') as directory:
            from pathlib import Path
            source = Path(directory)/'source'
            output = Path(directory)/'native.wav'
            source.write_bytes(raw)
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                capture_output=True, check=True, timeout=30)
            metadata = next(s for s in json.loads(probe.stdout)['streams']
                            if s['codec_type'] == 'audio')
            lossless = (metadata['codec_name'] in ('alac', 'flac')
                        or metadata['codec_name'].startswith('pcm_'))
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-map', '0:a:0',
                            *(['-t', str(seconds)] if seconds else []),
                            '-c:a', 'pcm_f32le', '-rf64', 'always', str(output)],
                           capture_output=True, check=True, timeout=120)
            with sf.SoundFile(output) as stream:
                yield stream, lossless
    else:
        with stream:
            yield stream, stream.subtype not in ('MPEG_LAYER_III', 'VORBIS', 'OPUS')


def canonical_decode(raw, seconds=None):
    with decoded_stream(raw, seconds) as (stream, lossless):
        rate, channels = stream.samplerate, stream.channels
        if channels not in (1, 2):
            raise ValueError('Grid requires mono or stereo source PCM')
        count = min(len(stream), round(seconds*rate)) if seconds else len(stream)
        output = np.empty((round(count*48000/rate)+4096, 2), np.float32)
        canonicalizer = AudioCanonicalizer()
        position = written = 0

        def collect(results):
            nonlocal written
            for result in results:
                if isinstance(result, CanonicalData):
                    samples = result.frame.samples
                    output[written:written+len(samples)] = samples
                    written += len(samples)

        while position < count:
            try:
                chunk = stream.read(min(16384, count-position), dtype='float32', always_2d=True)
            except sf.LibsndfileError:
                if seconds is None:
                    raise
                break  # A head prefix can end in a partial FLAC frame.
            if not len(chunk):
                break
            if not np.isfinite(chunk).all():
                raise ValueError('Non-finite source PCM')
            collect(canonicalizer.push(DataResult(DecodedSourceFrame(
                chunk, rate, channels, 'grid-file', position, False, None))))
            position += len(chunk)
        collect(canonicalizer.push(EndOfStream()))
        return output[:written], 48000, lossless, rate, channels


def decode(raw: bytes):
    return canonical_decode(raw)[:3]


def decode_head(raw, seconds=60):
    return canonical_decode(raw, seconds)[:3]


def stereo_attacks(audio, sr):
    # Combine envelopes, never PCM: hard-panned and opposite-polarity attacks survive.
    envelopes = [low_band_attacks(audio[:, channel], sr, allow_silence=True)
                 for channel in range(2)]
    energy = np.maximum(envelopes[0][0], envelopes[1][0])
    if not np.any(energy):
        raise ValueError('No low-band attacks found')
    return energy, envelopes[0][1], max(e[2] for e in envelopes)


def onset_envelope(y, sr):
    """Default librosa mel flux with bounded STFT intermediates."""
    frames = 1+len(y)//512
    mel = np.empty((128, frames), np.float32)
    for start in range(0, frames, 256):
        stop = min(frames, start+256)
        left, right = start*512-1024, (stop-1)*512+1024
        block = y[max(0, left):min(len(y), right)]
        if left < 0 or right > len(y):
            block = np.pad(block, (max(0, -left), max(0, right-len(y))))
        mel[:, start:stop] = librosa.feature.melspectrogram(
            y=block, sr=sr, n_fft=2048, hop_length=512, center=False)
    return librosa.onset.onset_strength(S=librosa.power_to_db(mel), sr=sr,
                                       hop_length=512, aggregate=np.median)


def global_tempo(onset, sr):
    """Accumulate the default eight-second tempogram mean in bounded blocks."""
    window = int(librosa.time_to_frames(8., sr=sr, hop_length=512))
    padded = np.pad(onset, (window//2, window//2), mode='linear_ramp')
    total = np.zeros(window, np.float64)
    for start in range(0, len(onset), 256):
        stop = min(len(onset), start+256)
        block = padded[start:stop+window-1]
        gram = librosa.feature.tempogram(onset_envelope=block, sr=sr, hop_length=512,
                                        win_length=window, center=False)
        total += gram.sum(axis=-1)
    return librosa.feature.tempo(tg=(total/len(onset))[:, None], sr=sr,
                                 hop_length=512, start_bpm=120)


def analyse_head(raw, seconds=60):
    """Provisional spectral-onset DP grid without whole-file JIT warm-up.

    A 64-band log-mel flux from canonical PCM supplies candidate periods. Dynamic
    programming scores their local beat paths; low-band energy and periodicity
    choose the path. The full analyser remains authoritative.
    """
    audio, sr, lossless, source_rate, source_channels = canonical_decode(raw, seconds)
    audio_fingerprint = fingerprint(audio).to_dict()
    y = audio.mean(axis=1)
    if len(y) < 2*sr or not np.isfinite(y).all():
        raise ValueError('Insufficient finite head audio')
    duration = len(y)/sr
    energy, hop, threshold = stereo_attacks(audio, sr)
    bands = {'low': energy,
             'mid': attack_envelope(audio, band=(150, 2000))[0],
             'high': attack_envelope(audio, band=(2000, 10000))[0]}
    step = hop/sr
    frequencies = np.linspace(0, sr/2, 2049)
    edges = 700*(10**(np.linspace(0, 2595*np.log10(1+5512.5/700), 66)/2595)-1)
    weights = np.maximum(0, np.minimum(
        (frequencies[None, :]-edges[:-2, None])/(edges[1:-1, None]-edges[:-2, None]),
        (edges[2:, None]-frequencies[None, :])/(edges[2:, None]-edges[1:-1, None])))
    # scipy's padded STFT can promote its FFT workspace to complex128.
    # Keep the exact head frame lattice while bounding that workspace too.
    frames = 1+int(np.ceil(len(y)/557))
    power = np.empty((64, frames), np.float32)
    for start in range(0, frames, 256):
        stop = min(frames, start+256)
        left, right = start*557-2048, (stop-1)*557+2048
        block = y[max(0, left):min(len(y), right)]
        if left < 0 or right > len(y):
            block = np.pad(block, (max(0, -left), max(0, right-len(y))))
        _, _, spectrum = stft(block, fs=sr, nperseg=4096, noverlap=4096-557,
                              boundary=None, padded=False)
        power[:, start:stop] = weights @ abs(spectrum)**2
    decibels = 10*np.log10(np.maximum(1e-12, power))
    onset = np.maximum(0, np.diff(decibels, axis=1)).mean(axis=0)
    autocorr = correlate(onset, onset, method='fft')[len(onset)-1:]
    odf_step = 557/sr
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
        values, offsets = attack_values(beats, energy, step)
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
    tempo_sections, rhythm_sections, downbeats = describe(
        beats, flags, tempo_sections, bands, hop/sr, duration)
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr,
                     float(np.clip(tempo, 60, 180)), tuple(map(float, beats)),
                     tuple(map(bool, flags)),
                     sections_for(beats, flags, duration)+tempo_sections+rhythm_sections,
                     confidence,
                     'content-v1' if lossless else 'unknown', provisional=True,
                     source_sample_rate=source_rate, source_channels=source_channels,
                     audio_fingerprint=audio_fingerprint, downbeats=downbeats)


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


def low_band_attacks(y, sr, *, allow_silence=False):
    if y.ndim == 2:
        return stereo_attacks(y, sr)
    energy, hop = attack_envelope(y, sample_rate=sr)
    peaks, _ = find_peaks(energy, distance=round(.16*sr/hop),
                          prominence=max(1e-9, float(np.max(energy))*.015))
    if not len(peaks):
        if allow_silence:
            return energy, hop, 0.
        raise ValueError('No low-band attacks found')
    strengths = energy[peaks]
    threshold = float(np.percentile(strengths, 90)) * .15
    return energy, hop, threshold


def attack_values(beats, energy, step, radius=.07):
    values, offsets = [], []
    for beat in beats:
        lo = max(0, int(np.ceil((beat-radius)/step)))
        hi = min(len(energy), int(np.floor((beat+radius)/step))+1)
        if hi <= lo:
            values.append(0.)
            offsets.append(0.)
            continue
        # Include envelope neighbours outside the search window so its edges
        # cannot manufacture local peaks. Equal-strength plateaus use their
        # scipy midpoint, with a deterministic earlier-peak tie break.
        start, stop = max(0, lo-1), min(len(energy), hi+1)
        peaks, _ = find_peaks(energy[start:stop])
        peaks = peaks+start
        peaks = peaks[(peaks >= lo) & (peaks < hi)]
        sufficient = peaks[energy[peaks] >= .5*float(np.max(energy[lo:hi]))]
        if len(sufficient):
            peak = int(sufficient[np.argmin(abs(sufficient*step-beat))])
            values.append(energy[peak])
            offsets.append(peak*step-beat)
        else:
            # Silence or a monotone window has no attack, rather than an
            # invented peak at the search boundary.
            values.append(0.)
            offsets.append(0.)
    return np.asarray(values, dtype=energy.dtype), np.asarray(offsets)


def kick_runs(beats, energy, step, period):
    return kick_evidence(beats, energy, step, period)[0]


def kick_evidence(beats, energy, step, period):
    """Hysteretic marginal evidence with immediate, coherent strong evidence."""
    on, offsets = attack_values(beats, energy, step)
    # Coherence is local evidence, not a veto on an entire tempo section.
    # A tiny resampling perturbation near a section MAD threshold must not
    # erase hundreds of otherwise supported bass drums. Preserve full weight up to
    # the former 20 ms MAD limit, then reduce it smoothly in each local window.
    windows = np.lib.stride_tricks.sliding_window_view(np.pad(offsets, (8, 8),
                                                             mode='edge'), 17)
    centre = np.median(windows, axis=1)
    scatter = np.median(abs(windows-centre[:, None]), axis=1)
    coherence = 1/(1+np.maximum(0, scatter/.02-1)**2)
    off, _ = attack_values(beats+period/2, energy, step)
    # Normalise contrast to this tempo section: off-beat bass can be louder
    # than a bass drum, so a universal absolute ratio is not reliable.
    reference = float(np.median(on))/max(1e-12, float(np.median(off)))
    window_on = median_filter(on*coherence, size=9, mode='nearest')
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
    # Runs with bass drums establish level anchors. A local median can follow
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


def interval_outliers(beats):
    """Intervals outside 25% of the nine-interval local median."""
    intervals = np.diff(beats)
    local = median_filter(intervals, size=9, mode='nearest')
    return np.flatnonzero(abs(intervals-local) > .25*local+1e-9)


def repair_tracked_beats(beats, energy, step):
    """Re-place anomalous passages using eight surrounding non-outlier beats.

    Preserve the count. Snap each fitted position to the nearest sufficient
    bass drum attack when available. Commit a passage only when its intervals
    and both seams satisfy the local consistency criterion.
    """
    result = np.asarray(beats).copy()
    if len(result) < 10:
        return result
    intervals = np.diff(result)
    if np.std(intervals)/np.mean(intervals) < .04-1e-9:
        # The existing lattice fit owns rigid timing; repair expressive paths.
        return result
    blocked = set()
    for _ in range(len(result)):
        bad = interval_outliers(result)
        pending = [int(index) for index in bad if int(index) not in blocked]
        if not pending:
            break
        target = pending[0]
        lo, hi = target, target+1
        excluded = set(map(int, np.r_[bad, bad+1]))
        repaired = False
        for _ in range(len(result)):
            left = [index for index in range(lo) if index not in excluded][-4:]
            right = [index for index in range(hi+1, len(result)) if index not in excluded][:4]
            if len(left)+len(right) < 8:
                break
            anchors = np.asarray(left+right)
            slope, phase = np.polyfit(anchors, result[anchors], 1)
            if slope <= 0:
                break
            predicted = phase+np.arange(lo, hi+1)*slope
            values, offsets = attack_values(predicted, energy, step)
            proposed = result.copy()
            proposed[lo:hi+1] = predicted+np.where(values > 0, offsets, 0.)
            remaining = interval_outliers(proposed)
            touching = remaining[(remaining >= max(0, lo-1)) & (remaining <= hi)]
            if not len(touching) and np.all(np.diff(proposed) > 0):
                result = proposed
                repaired = True
                break
            grow_left = bool(np.any(touching <= lo))
            grow_right = bool(np.any(touching >= hi-1))
            if not grow_left and not grow_right:
                grow_left = grow_right = True
            previous = lo, hi
            if grow_left:
                lo = max(0, lo-1)
            if grow_right:
                hi = min(len(result)-1, hi+1)
            if previous == (lo, hi):
                break
        if not repaired:
            blocked.add(target)
    return result


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
    audio, sr, lossless, source_rate, source_channels = canonical_decode(raw)
    audio_fingerprint = fingerprint(audio).to_dict()
    y = audio.mean(axis=1)
    duration = len(y) / sr
    if duration < 2 or not np.isfinite(y).all():
        raise ValueError('Audio must contain at least two seconds of finite samples')
    energy, hop, threshold = stereo_attacks(audio, sr)
    bands = {'low': energy,
             'mid': attack_envelope(audio, band=(150, 2000))[0],
             'high': attack_envelope(audio, band=(2000, 10000))[0]}
    onset = onset_envelope(y, sr)
    del y, audio
    _, tracked = librosa.beat.beat_track(onset_envelope=onset, bpm=global_tempo(onset, sr),
                                         sr=sr, hop_length=512, start_bpm=120, tightness=100,
                                         units='time', trim=False)
    if len(tracked) < 3:
        raise ValueError('Insufficient beats')
    tracked = repair_tracked_beats(tracked, energy, hop/sr)
    tempo = 60 / float(np.median(np.diff(tracked)))
    # Tracker hop quantisation may straddle an endpoint of the tempo prior.
    candidates = sorted({float(np.clip(tempo*scale, 60, 180)) for scale in (.5, 1, 2)
                         if 59.4 <= tempo*scale <= 181.8})
    if not candidates:
        raise ValueError('No tempo in 60–180 BPM range')
    # Only lags around the 60–180 BPM candidates are consumed. Avoid a
    # full FFT and its complex work arrays for the duration-length envelope.
    autocorrelation = np.zeros(round(1.01*sr/hop)+4, np.float32)
    for lag in range(1, len(autocorrelation)):
        autocorrelation[lag] = np.dot(energy[lag:], energy[:-lag])
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
    tempo_sections, rhythm_sections, downbeats = describe(
        beats, flags, tempo_sections, bands, hop/sr, duration)
    return TrackGrid(VERSION, hashlib.sha256(raw).hexdigest(), duration, sr, float(tempo),
                     tuple(map(float, beats)), tuple(map(bool, flags)),
                     sections_for(beats, flags, duration)+tempo_sections+rhythm_sections,
                     confidence,
                     'content-v1' if lossless else 'unknown',
                     source_sample_rate=source_rate, source_channels=source_channels,
                     audio_fingerprint=audio_fingerprint, downbeats=downbeats)


def limit_address_space(duration, *, head=False):
    """Linux worker only: reserve duration-scaled scratch above imported VM.

    Never apply a process-wide rlimit in callers of the public Python API.
    The LMS adapter always launches this CLI in a dedicated child.
    """
    import resource
    from pathlib import Path

    # Materialise lazy DSP/JIT imports before measuring the imported VM floor.
    # This fixed-size warm-up is independent of the source duration/rate.
    if not head:
        onset_envelope(np.zeros(4096, np.float32), 48000)
        librosa.beat.beat_track(onset_envelope=np.ones(200, np.float32), sr=48000, bpm=120)
    baseline = int(Path('/proc/self/statm').read_text().split()[0])*resource.getpagesize()
    bound = min(2*1024**3, baseline+384*1024**2+round(duration*1024**2))
    if baseline >= bound:
        raise ValueError('Imported address space exceeds grid worker memory budget')
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        bound = min(bound, hard)
    resource.setrlimit(resource.RLIMIT_AS, (bound, hard))
    return bound


def main():
    import logging
    import mmap
    import os
    import sys
    from pathlib import Path

    from .worker import THREAD_VARIABLES

    logging.warning('Grid worker thread budget=%s',
                    {name: os.environ.get(name) for name in THREAD_VARIABLES})
    profile = "--profile-memory" in sys.argv[2:]
    if profile:
        import tracemalloc
        tracemalloc.start()
    head = "--head" in sys.argv[2:]
    path = Path(sys.argv[1])
    try:
        # Probe before reading original bytes or allocating canonical PCM. The
        # decoder child inherits the same address-space ceiling.
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-of', 'json',
                                str(path)], capture_output=True, check=True, timeout=30)
        duration = float(json.loads(probe.stdout)['format']['duration'])
        if not np.isfinite(duration) or duration <= 0:
            raise ValueError('Missing finite duration for grid memory budget')
        bound = limit_address_space(min(60, duration) if head else duration, head=head)
        logging.warning('Grid worker memory bound=%d bytes duration=%.3fs', bound, duration)
        with (path.open('rb') as source,
              mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as raw):
            function = analyse_head if head else analyse
            print(json.dumps(function(raw).to_dict(), allow_nan=False))
    except (MemoryError, OSError, ValueError, subprocess.SubprocessError) as error:
        logging.error('Grid analysis unavailable; retaining tracker: %s: %s',
                      type(error).__name__, error)
        return 1
    finally:
        import resource
        logging.warning('Grid worker peak_rss_bytes=%d',
                        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        if profile:
            logging.warning('Grid worker traced current/peak bytes=%s',
                            tracemalloc.get_traced_memory())
            for allocation in tracemalloc.take_snapshot().statistics('lineno')[:10]:
                logging.warning('Grid worker allocation: %s', allocation)
            tracemalloc.stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
