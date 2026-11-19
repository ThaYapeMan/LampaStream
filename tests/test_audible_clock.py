"""Offline unit coverage for the ROUTE-01 clock foundation (not engine integration)."""
from types import SimpleNamespace

import pytest

from lampastream.audible_clock import (
    AirPlayAudibleClock,
    LmsAudibleClock,
    SqueezeboxAudibleClock,
    YeneyRoomAudibleClock,
    lampastream_own_player_clock,
    lms_clock_for_model,
)
from lampastream.latency import NoLatencyProbe
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
    assert (point.lookahead_s > 0) == (kind is AirPlayAudibleClock)
    assert clock.generation == (2, 0)


def test_zero_lookahead_clock_points_are_equal():
    probe = SimpleNamespace(current_delay_ms=lambda: 0)
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=1., play_monotonic=1.)
    a = LmsAudibleClock(probe)
    b = AirPlayAudibleClock(probe, SimpleNamespace(tap_source='early tap'), lookahead=0.)
    assert a.at(480, 0, features, 5.) == b.at(480, 0, features, 5.)


def test_legacy_reader_name_is_a_compatibility_alias():
    assert SqueezeliteShmStereoSource is YeneyCoreShmStereoSource


@pytest.mark.parametrize('model,modelname,expected', [
    ('yeney', 'YeneY', YeneyRoomAudibleClock),
    ('yeney', 'Sonos Port (YeneY)', YeneyRoomAudibleClock),
    ('yeney', 'Sonos Play:1 (YeneY)', YeneyRoomAudibleClock),
    ('yeney', 'Sonos (YeneY)', YeneyRoomAudibleClock),
    ('baby', 'Squeezebox Radio', SqueezeboxAudibleClock),
    ('squeezelite', 'Sonos Port', LmsAudibleClock),
    ('squeezelite', 'YeneY', LmsAudibleClock),
    ('unknown', 'Sonos', LmsAudibleClock),
    ('', 'YeneY', LmsAudibleClock),
    (None, 'YeneY', LmsAudibleClock),
    ('YeneY ', 'Sonos Port (YeneY)', YeneyRoomAudibleClock),
])
def test_room_clock_uses_player_type(model, modelname, expected):
    from lampastream.lms_status import LmsPlayerStatus

    status = LmsPlayerStatus(model=model, modelname=modelname)
    probe = SimpleNamespace(current_delay_ms=lambda: 350, player_delay=200)
    clock = lms_clock_for_model(status.model, probe)
    assert type(clock) is expected
    assert clock.model == ((model or '').strip().lower() or 'unknown LMS model')
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=10.)
    # The measured offset already includes the reported pipeline delay.
    assert clock.at(0, 0, features, 11.).audible == pytest.approx(10.350)
    if expected is YeneyRoomAudibleClock:
        assert clock.kind == 'yeney-sonos'
        assert clock.reported_pipeline_delay_ms == 200
    elif expected is SqueezeboxAudibleClock:
        assert clock.kind == 'squeezebox'


def test_normal_native_player_clock_adds_room_offset_without_using_receipt_time():
    probe = SimpleNamespace(current_delay_ms=lambda: 200)
    clock = LmsAudibleClock(probe)
    features = AudioFeatures([], 0, 0, 0, 0, received_monotonic=10.5, play_monotonic=10.)
    assert clock.at(480, 0, features, 20.).audible == pytest.approx(10.21)
    assert clock.lookahead_s == 0


@pytest.mark.parametrize('probe,timing,stamps,audible', [
    (NoLatencyProbe(), None, {'play_monotonic': 10.}, 10.01),
    (SimpleNamespace(current_delay_ms=lambda: 200), None,
     {'received_monotonic': 10.}, 10.209999999999999),
    (SimpleNamespace(config=SimpleNamespace(trim_ms=50)),
     SimpleNamespace(tap_source='LMS head start'), {'play_monotonic': 10.}, 10.06),
])
def test_own_player_clock_preserves_recorded_mapping(probe, timing, stamps, audible):
    # Outputs recorded using the initial clock factory at 6d53a77.
    clock = lampastream_own_player_clock(probe, timing)
    assert type(clock) is YeneyRoomAudibleClock
    assert clock.kind == 'yeney-sonos'
    assert clock.model == 'lampastream own player'
    assert clock.reported_pipeline_delay_ms is None
    features = AudioFeatures([], 0, 0, 0, 0, **stamps)
    point = clock.at(480, 0, features, 20.)
    assert point.audible == audible
    assert point.lookahead_s == 0.
