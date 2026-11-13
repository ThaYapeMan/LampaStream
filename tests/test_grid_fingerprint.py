"""Landmarks identify sound, survive gain/polarity, and map crops explicitly."""
import numpy as np
import pytest

from lampastream.grid.fingerprint import Fingerprint, fingerprint, match


def signal(seed=14, seconds=24):
    rng = np.random.default_rng(seed)
    audio = np.zeros((48000*seconds, 2), np.float32)
    time = np.arange(24000)/48000
    for second in range(2*seconds):
        frequencies = rng.uniform(300, 10000, 4)
        tone = sum(np.sin(2*np.pi*frequency*time) for frequency in frequencies)
        tone *= np.exp(-time*8)
        audio[second*24000:(second+1)*24000] = tone[:, None]*rng.uniform(.1, .2, (1, 2))
    return audio


def test_same_sound_gain_and_phase_not_container_bytes():
    audio = signal()
    first = fingerprint(audio)
    changed = audio*np.array([.7, -.7], np.float32)
    result = match(fingerprint(changed), first)
    assert result is not None and result.duration_agrees
    assert result.offset_s == pytest.approx(0, abs=.02)
    assert result.confidence > .9
    assert Fingerprint.from_dict(first.to_dict()) == first


def test_crop_is_segment_match_not_same_master():
    audio = signal()
    result = match(fingerprint(audio[6*48000:18*48000]), fingerprint(audio))
    assert result is not None
    assert result.offset_s == pytest.approx(6, abs=.02)
    assert not result.duration_agrees


def test_different_sound_and_repeating_clicks_are_not_identity():
    assert match(fingerprint(signal(1)), fingerprint(signal(2))) is None
    audio = np.zeros((12*48000, 2), np.float32)
    tone = np.sin(np.arange(4800)*2*np.pi*80/48000).astype(np.float32)
    for sample in range(0, len(audio), 24000):
        audio[sample:sample+4800] = tone[:, None]
    assert match(fingerprint(audio), fingerprint(audio)) is None


def test_silence_and_invalid_fingerprints():
    silence = fingerprint(np.zeros((12*48000, 2), np.float32))
    assert not silence.landmarks
    assert match(silence, silence) is None
    with pytest.raises(ValueError):
        Fingerprint.from_dict(dict(version=99, duration=12, landmarks=[]))
    with pytest.raises(ValueError):
        fingerprint(np.zeros((100, 2), np.float32))
