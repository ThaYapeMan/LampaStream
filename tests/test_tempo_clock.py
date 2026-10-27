import pytest

from lampastream.tempo_clock import TempoClock


@pytest.mark.parametrize('bpm', [100, 120, 122, 128, 174])
def test_clock_locks_within_four_seconds_and_holds_silent_tempo(bpm):
    clock = TempoClock()
    locked_at = None
    for n in range(24):
        t = .5+n*60/bpm
        clock.trigger(t, 1 if n % 4 == 0 else .5)
        if clock.locked and locked_at is None:
            locked_at = t-.5
    assert clock.tempo_bpm == pytest.approx(bpm, abs=1e-8)
    assert locked_at <= 4
    before = clock.confidence
    for n in range(1, 201):
        clock.update(t+n*.01, gate=False)
    assert not clock.locked
    assert clock.tempo_bpm == pytest.approx(bpm, abs=1e-8)
    assert clock.confidence < before
    assert clock.bar_position(t) == 3


def test_tempo_change_relocks_within_four_seconds():
    clock = TempoClock()
    for n in range(12):
        clock.trigger(n*.5)
    locked_at = None
    for n in range(12):
        t = 6+n*60/128
        clock.trigger(t)
        if clock.locked and abs(clock.tempo_bpm-128) <= 1 and locked_at is None:
            locked_at = t-6
    assert locked_at is not None and locked_at <= 4
