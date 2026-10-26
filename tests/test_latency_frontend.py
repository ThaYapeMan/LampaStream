"""Independent onset resolution preserves continuous spectrum and hop clocks."""
import numpy as np
import pytest

from lampastream.pcm_source import PcmStft
from lampastream.sync_engine import StereoMagStft


@pytest.mark.parametrize('window', [256, 512, 1024])
def test_short_window_chunk_invariant(window):
    pcm = np.random.default_rng(71).normal(size=(4800, 2)).astype(np.float32)
    whole = StereoMagStft(48000, window, right_aligned=True).push(pcm)
    stream = StereoMagStft(48000, window, right_aligned=True)
    split = [mag for start in range(0, len(pcm), 100)
             for mag in stream.push(pcm[start:start+100])]
    assert len(whole) == len(split) == 10
    for a, b in zip(whole, split, strict=True):
        np.testing.assert_array_equal(a, b)
    stream.reset()
    for a, b in zip(whole, stream.push(pcm), strict=True):
        np.testing.assert_array_equal(a, b)


def test_long_stft_unchanged():
    pcm = np.random.default_rng(9).normal(size=4800).astype(np.float32)
    frames = PcmStft(48000).push(pcm)
    expected = [np.abs(np.fft.rfft(pcm[i:i+2048] * np.hamming(2048).astype(np.float32)))
                .astype(np.float32) for i in range(0, len(pcm)-2048+1, 480)]
    np.testing.assert_array_equal(frames, expected)
