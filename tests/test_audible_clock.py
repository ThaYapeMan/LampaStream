"""Offline unit coverage for the ROUTE-01 clock foundation (not engine integration)."""
from types import SimpleNamespace

import pytest

from lampastream.audible_clock import AirPlayAudibleClock, LmsAudibleClock
from lampastream.pcm_source import SqueezeliteShmStereoSource, YeneyCoreShmStereoSource
from lampastream.types import AudioFeatures


def test_causal_mapping_uses_canonical_positions_and_measured_room_offset():
    probe = SimpleNamespace(current_delay_ms=lambda: 200)
    clock = LmsAudibleClock(probe)
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=10.)
    assert clock.at(480, 0, features, 20.).audible == pytest.approx(10.21)
    assert clock.lookahead_s == 0


@pytest.mark.parametrize('kind,mode', [(LmsAudibleClock, 'LMS head start'),
                                      (AirPlayAudibleClock, 'early tap')])
def test_player_provenance_and_trim_remain_in_clock_mapping(kind, mode):
    probe = SimpleNamespace(config=SimpleNamespace(trim_ms=50))
    timing = SimpleNamespace(tap_source=mode, tap_generation=2)
    clock = kind(probe, timing)
    features = AudioFeatures([], 0, 0, 0, 0, play_monotonic=10.)
    point = clock.at(480, 0, features, 1.)
    assert point.audible == pytest.approx(10.06)
    assert point.lookahead_s > 0
    assert clock.generation == 2


def test_zero_lookahead_clock_points_are_equal():
    probe = SimpleNamespace(current_delay_ms=lambda: 0)
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=1., play_monotonic=10.)
    a = LmsAudibleClock(probe)
    b = AirPlayAudibleClock(probe, SimpleNamespace(tap_source='early tap'), lookahead=0.)
    assert a.at(480, 0, features, 5.) == b.at(480, 0, features, 5.)


def test_legacy_reader_name_is_a_compatibility_alias():
    assert SqueezeliteShmStereoSource is YeneyCoreShmStereoSource
