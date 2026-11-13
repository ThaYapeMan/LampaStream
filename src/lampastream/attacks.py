"""Shared causal attack measurement on canonical PCM.

Each channel is filtered separately; positive 5 ms RMS rises are combined by
maximum, preserving hard-panned and opposite-polarity attacks. Filter state,
partial windows and previous RMS belong to one analysis epoch.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt


class AttackDetector:
    def __init__(self, *, sample_rate=48000, channels=2, band=(40, 150)):
        if channels not in (1, 2) or sample_rate <= 2*band[1]:
            raise ValueError('Invalid attack detector format')
        self.hop = round(sample_rate*.005)
        self.channels = channels
        self.sos = butter(4, band, btype='bandpass', fs=sample_rate,
                          output='sos').astype(np.float32)
        self.reset()

    def reset(self):
        self.state = np.zeros((len(self.sos), 2, self.channels), np.float32)
        self.carry = np.empty((0, self.channels), np.float32)
        self.previous = np.zeros(self.channels, np.float32)
        self.position = 0

    def feed(self, pcm):
        samples = np.asarray(pcm, dtype=np.float32)
        if samples.ndim == 1 and self.channels == 1:
            samples = samples[:, None]
        if samples.ndim != 2 or samples.shape[1] != self.channels:
            raise ValueError('Attack detector channel mismatch')
        if not len(samples):
            return np.empty(0, np.float32)
        filtered, self.state = sosfilt(self.sos, samples, axis=0, zi=self.state)
        if len(self.carry):
            filtered = np.concatenate((self.carry, filtered))
        count = len(filtered)//self.hop
        self.carry = filtered[count*self.hop:].copy()
        if not count:
            return np.empty(0, np.float32)
        complete = filtered[:count*self.hop]
        np.square(complete, out=complete)
        # A contiguous channel window uses the same float32 reduction order
        # for one-hop feeds and whole-track calls.
        rms = np.column_stack([
            np.sqrt(np.mean(complete[:, channel].copy().reshape(count, self.hop), axis=1))
            for channel in range(self.channels)])
        rises = np.maximum(0, np.diff(rms, axis=0, prepend=self.previous[None, :]))
        self.previous = rms[-1].copy()
        self.position += count*self.hop
        return np.max(rises, axis=1)


def attack_envelope(pcm, *, sample_rate=48000, band=(40, 150)):
    channels = pcm.shape[1] if pcm.ndim == 2 else 1
    detector = AttackDetector(sample_rate=sample_rate, channels=channels, band=band)
    # Bound filtering scratch independently of a track's duration.
    result = np.empty(len(pcm)//detector.hop, np.float32)
    written = 0
    for start in range(0, len(pcm), 16384):
        values = detector.feed(pcm[start:start+16384])
        result[written:written+len(values)] = values
        written += len(values)
    return result, detector.hop
