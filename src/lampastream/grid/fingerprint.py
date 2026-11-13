"""Clean-room spectral landmark fingerprints of canonical PCM; no models.

Peaks are paired across time. Matching votes for a constant segment offset,
then checks coverage and duration. Metadata and container bytes play no role.
The format is intentionally versioned independently of the beat analyser.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import maximum_filter

FINGERPRINT_VERSION = 1
RATE = 48000
HOP = 960
WINDOW = 4096


@dataclass(frozen=True)
class Fingerprint:
    duration: float
    landmarks: tuple[tuple[int, int], ...]
    version: int = FINGERPRINT_VERSION

    def to_dict(self):
        return dict(duration=self.duration, landmarks=self.landmarks, version=self.version)

    @classmethod
    def from_dict(cls, data):
        if data['version'] != FINGERPRINT_VERSION or not np.isfinite(data['duration']):
            raise ValueError('Unsupported fingerprint')
        if data['duration'] <= 0:
            raise ValueError('Invalid fingerprint duration')
        landmarks = tuple(tuple(pair) for pair in data['landmarks'])
        if any(len(pair) != 2 or not all(type(v) is int and v >= 0 for v in pair)
               for pair in landmarks):
            raise ValueError('Invalid fingerprint landmarks')
        return cls(data['duration'], landmarks)


@dataclass(frozen=True)
class SegmentMatch:
    offset_s: float
    confidence: float
    matched_landmarks: int
    duration_agrees: bool


def fingerprint(pcm: np.ndarray) -> Fingerprint:
    """Bound FFT scratch to 256 hops and combine channel power, never PCM."""
    if (pcm.ndim != 2 or pcm.shape[1] != 2 or len(pcm) < WINDOW
            or not np.isfinite(pcm).all()):
        raise ValueError('Fingerprint requires finite canonical stereo PCM')
    window = np.hanning(WINDOW).astype(np.float32)
    peaks = []
    frames = 1+(len(pcm)-WINDOW)//HOP
    # Log frequency bins make minor codec/resampler changes tolerant without
    # discarding the pair's distinctive interval and frequency relationship.
    bins = np.arange(8, WINDOW//2)
    for start in range(0, frames, 256):
        stop = min(frames, start+256)
        block = pcm[start*HOP:(stop-1)*HOP+WINDOW]
        views = np.lib.stride_tricks.sliding_window_view(block, WINDOW, axis=0)[::HOP]
        spectrum = np.fft.rfft(views*window, axis=-1)
        power = np.sum(abs(spectrum)**2, axis=1)[:, bins]
        local = maximum_filter(power, size=(1, 9), mode='nearest')
        for frame, row in enumerate(power):
            candidates = np.flatnonzero((row == local[frame]) & (row > row.max()*.025))
            strongest = sorted(candidates, key=lambda i: float(row[i]), reverse=True)[:5]
            for index in strongest:
                frequency = int(round(48*np.log2(bins[index]/8)))
                peaks.append((start+frame, frequency))
    landmarks = []
    for index, (time, frequency) in enumerate(peaks):
        targets = []
        for target_index in range(index+1, len(peaks)):
            target_time, target_frequency = peaks[target_index]
            delta = target_time-time
            if delta > 75:
                break
            if 5 <= delta <= 75:
                targets.append((delta, target_frequency))
                if len(targets) == 4:
                    break
        for delta, target_frequency in targets:
            # Fixed integer packing, independent of Python's randomised hash.
            token = (frequency << 18) | (target_frequency << 8) | delta
            landmarks.append((token, time))
    return Fingerprint(len(pcm)/RATE, tuple(landmarks))


def match(query: Fingerprint, candidate: Fingerprint, *, duration_tolerance=1.,
          minimum_seconds=8.) -> SegmentMatch | None:
    """A matched crop returns an offset, never an unshifted full-track identity.

    Callers may attach a full grid only with duration_agrees and near-zero
    offset; an edit requires explicit segment mapping or clean rejection.
    Repeated/tonal landmarks are excluded to avoid confident matches on clicks.
    """
    if (query.version != candidate.version
            or min(query.duration, candidate.duration) < minimum_seconds):
        return None
    by_token = defaultdict(list)
    for token, time in candidate.landmarks:
        by_token[token].append(time)
    votes = Counter()
    pairs = []
    eligible = 0
    for token, time in query.landmarks:
        occurrences = by_token.get(token, ())
        if not 1 <= len(occurrences) <= 8:
            continue
        eligible += 1
        for target in occurrences:
            offset = target-time
            votes[offset] += 1
            pairs.append((time, offset, token))
    if not votes:
        return None
    offset, _ = votes.most_common(1)[0]
    agreed = [(time, token) for time, difference, token in pairs if abs(difference-offset) <= 1]
    distinct = {token for _, token in agreed}
    seconds = {int(time*HOP/RATE) for time, _ in agreed}
    span = (max(seconds)-min(seconds)+1) if seconds else 0
    if len(distinct) < 24 or span < minimum_seconds or len(seconds) < .6*minimum_seconds:
        return None
    confidence = min(1., len(agreed)/max(1, eligible))
    if confidence < .08:
        return None
    return SegmentMatch(offset*HOP/RATE, confidence, len(agreed),
                        abs(query.duration-candidate.duration) <= duration_tolerance)
