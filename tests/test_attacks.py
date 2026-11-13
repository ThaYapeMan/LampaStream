"""Chunk-independent shared attack measurements against the original formula."""
import numpy as np
from scipy.signal import butter, sosfilt

from lampastream.attacks import AttackDetector, attack_envelope


def test_chunking_channels_and_reset():
    rng = np.random.default_rng(18)
    audio = rng.normal(0, .1, (48000, 2)).astype(np.float32)
    expected, hop = attack_envelope(audio)
    channels = []
    for channel in range(2):
        filtered = sosfilt(butter(4, [40, 150], fs=48000, btype='bandpass',
                                  output='sos').astype(np.float32), audio[:, channel])
        np.square(filtered, out=filtered)
        rms = np.sqrt(np.mean(filtered.reshape(-1, hop), axis=1))
        channels.append(np.maximum(0, np.diff(rms, prepend=np.float32(0))))
    np.testing.assert_allclose(expected, np.maximum(*channels), atol=1e-7, rtol=1e-5)
    for size in (17, 480, 4096):
        detector = AttackDetector()
        actual = np.concatenate([detector.feed(audio[start:start+size])
                                 for start in range(0, len(audio), size)])
        np.testing.assert_array_equal(actual, expected)
        detector.reset()
        np.testing.assert_array_equal(detector.feed(audio), expected)
    anti_phase = np.column_stack((audio[:, 0], -audio[:, 0]))
    np.testing.assert_array_equal(attack_envelope(anti_phase)[0],
                                  attack_envelope(audio[:, 0])[0])


def test_live_detector_uses_the_offline_measurement_and_resets():
    from lampastream.spectrum_engine import SharedAnalysisFrame
    from lampastream.sync_engine import BeatDetector
    rng = np.random.default_rng(20)
    audio = rng.normal(0, .05, (48000, 2)).astype(np.float32)
    detector = BeatDetector('combined', .1, .9, 3, 2, 250, 2000)
    expected, _ = attack_envelope(audio)
    measured = []
    for start in range(0, len(audio), 1024):
        chunk = audio[start:start+1024]
        detector.feed(SharedAnalysisFrame(chunk, [], 'epoch', start, start+len(chunk), []))
        measured.extend(detector.attack_frames)
    assert [sample for sample, _ in measured] == list(range(0, 48000, 240))
    np.testing.assert_array_equal([value for _, value in measured], expected)
    detector.reset()
    detector.feed(SharedAnalysisFrame(audio, [], 'new', 0, 48000, []))
    np.testing.assert_array_equal([value for _, value in detector.attack_frames], expected)


def test_grid_confirmation_keeps_peak_across_chunks_and_discards_old_epoch():
    from lampastream.grid.prior import GridPrior
    prior = GridPrior()
    prior.observe_attacks([(0, 0.), (240, 1.)])
    assert not prior.onsets
    prior.observe_attacks([(480, 0.)])
    assert list(prior.onsets) == [.005]
    prior.reset_attacks()
    prior.onsets.clear()
    prior.observe_attacks([(0, 0.)])
    assert not prior.onsets
