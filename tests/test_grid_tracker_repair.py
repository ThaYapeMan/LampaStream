"""Local passage repair moves misplaced beats without changing their count."""
import numpy as np

from lampastream.grid.analyser import interval_outliers, repair_tracked_beats


def attack_envelope(beats, duration):
    energy = np.zeros(round(duration/.005), np.float32)
    energy[np.rint(beats/.005).astype(int)] = 1
    return energy


def test_misplaced_beat_uses_surrounding_fit_and_real_attack():
    expected = .5+np.arange(40)*.75
    tracked = expected.copy()
    tracked[20] += .25
    energy = attack_envelope(expected, expected[-1]+1)
    assert interval_outliers(tracked).tolist() == [19, 20]
    repaired = repair_tracked_beats(tracked, energy, .005)
    assert len(repaired) == len(tracked)
    np.testing.assert_allclose(repaired, expected, atol=1e-9)
    assert not len(interval_outliers(repaired))
    assert tracked[20] == expected[20]+.25  # Input ownership is preserved.


def test_no_attack_keeps_the_local_fit_without_inserting_a_beat():
    expected = .5+np.arange(40)*.75
    tracked = expected.copy()
    tracked[20] -= .25
    repaired = repair_tracked_beats(tracked, np.zeros(6500, np.float32), .005)
    assert len(repaired) == len(tracked)
    np.testing.assert_allclose(repaired, expected, atol=1e-9)


def test_regular_and_expressive_fixtures_are_unchanged_even_in_silent_passages():
    rigid = .5+np.arange(60)*.5
    intervals = .5*(1+.04*np.tile([-1, 1], 30))
    expressive = .5+np.r_[0, np.cumsum(intervals)]
    for tracked in (rigid, expressive):
        energy = attack_envelope(tracked, tracked[-1]+1)
        energy[round(10/.005):round(15/.005)] = 0
        repaired = repair_tracked_beats(tracked, energy, .005)
        assert np.array_equal(repaired, tracked)
