"""LAT-03 room sessions: signed offsets, continuous calibration and shared beat time."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from replay_chain import Replay, parser

from lampastream.audible_clock import AirPlayAudibleClock, YeneyRoomAudibleClock
from lampastream.latency import AutoLatencyProbe, FollowPositionContext
from lampastream.lms_status import _parse_status
from lampastream.models import PlayerLatency
from lampastream.track_position import LmsTrackPositionSource
from lampastream.types import AudioFeatures


@pytest.mark.parametrize('saved,error', [(0, .2), (.2, 0), (-.2, 0)])
def test_room_session_correct_from_remembered_start_or_converges_without_jumps(saved, error):
    now = [0.]
    room = SimpleNamespace(latency_context=lambda: FollowPositionContext(True, True, True, 1, 1))
    probe = AutoLatencyProbe(PlayerLatency('room', strategy='auto',
                             measured_delay_ms=round(saved*1000)), room, Mock(),
                             clock=lambda: now[0])
    clock = YeneyRoomAudibleClock(probe)
    offsets = []
    for tick in range(1801):
        now[0] = tick / 20
        if tick % 60 == 0:
            probe.accept(saved + error, now[0])
        # A sample at room time now is played early by own-follow position.
        features = AudioFeatures([], 0, 0, 0, 0,
                                 play_monotonic=now[0]-saved-error,
                                 received_monotonic=now[0]+.04)
        offsets.append(clock.at(0, 0, features, now[0]).audible-now[0])
    assert np.max(np.abs(np.diff(offsets))) <= .005 / 20 + 1e-9
    assert abs(offsets[-1]) < .001
    assert clock.generation == (0, 0)  # a smooth refinement never retires queued scenes
    if not error:
        assert max(abs(v) for v in offsets) < .015
    print(f'saved={saved:+.3f}s error={error:+.3f}s: '
          f'max correction={max(abs(v) for v in np.diff(offsets))*1000:.3f}ms/50ms; '
          f'final={offsets[-1]*1000:.3f}ms')


def test_subscription_anchor_refines_without_a_step_and_resets_for_seek(monkeypatch):
    now = [100.]
    monkeypatch.setattr('lampastream.track_position.time.monotonic', lambda: now[0])
    source = LmsTrackPositionSource('host', lambda: 'room')
    source.seed('room', _parse_status('mode:play title:Song time:0 duration:300'), now[0])
    now[0] += 10
    source.seed('room', _parse_status('mode:play title:Song time:10.2 duration:300'), now[0])
    assert source.read().position_now() == 10
    positions = []
    for i in range(801):
        now[0] = 110 + i / 20
        positions.append(source.read().position_now() - (now[0]-100))
    assert max(abs(v) for v in np.diff(positions)) <= .000250001
    assert positions[-1] == pytest.approx(.2)
    source.seed('room', _parse_status('mode:play title:Song time:90 duration:300'), now[0])
    assert source.read().position_now() == 90


def test_real_128_bpm_detection_times_agree_across_room_clocks(tmp_path):
    """Same canonical publications, two physical provenance mappings after lock."""
    from pathlib import Path

    args = parser().parse_args([
        '--input', str(Path(__file__).parent/'fixtures/replay/clicks-128.wav'),
        '--config', str(Path(__file__).parent/'fixtures/tracker-baseline-config.json'),
        '--route', 'normal', '--out', str(tmp_path/'trace')])
    replay = Replay(args)
    rate = 48000
    pcm = np.zeros(rate * 40, dtype=np.float32)
    t = np.arange(4800) / rate
    kick = .9 * np.sin(2*np.pi*60*t) * np.exp(-t*55)
    for stamp in np.arange(.5, 39.7, 60/128):
        start = round(stamp*rate)
        pcm[start:start+len(kick)] += kick
    pcm = np.column_stack([pcm, pcm])
    try:
        replay.analyse(pcm, rate)
        # Real detector outputs carry canonical candidate positions. Mapping is
        # independent of when delayed publications are delivered to either route.
        events = [(record, event) for record in replay.records
                  for event in record.features.onset_events
                  if event.kind == 'beat' and record.features.tempo_locked and not event.predicted]
        assert events
        probe = SimpleNamespace(current_delay_ms=lambda: -200)
        lms = YeneyRoomAudibleClock(probe)
        air = AirPlayAudibleClock(timing=SimpleNamespace(tap_source='early tap'), lookahead=1.5)
        differences = []
        for record, event in events:
            features = record.features
            sample = event.candidate_sample
            reference = record.sample_pos
            # Independent transport anchors: the LMS virtual player lags 200ms;
            # AirPlay provides the intended room playback time directly.
            from dataclasses import replace
            own = replace(features, timing_generation=None, play_monotonic=100+reference/48000+.2)
            room = replace(features, timing_generation=None, play_monotonic=100+reference/48000)
            a = lms.at(sample, reference, own, 100).audible
            b = air.at(sample, reference, room, 100).audible
            differences.append(abs(a-b))
        assert max(differences) < .010
        print(f'{len(events)} real locked 128 BPM detections: '
              f'max LMS/AirPlay difference={max(differences)*1000:.6f}ms')
    finally:
        replay.pipeline.stop()


def test_signed_room_estimate_is_remembered_on_restart(tmp_path):
    from lampastream.storage import Storage

    storage = Storage(tmp_path/'config.json')
    config = PlayerLatency('room', strategy='auto')
    storage.save_player_latency(config)

    def persist(measured, stamp):
        entry = storage.get_player_latency('room')
        entry.measured_delay_ms, entry.measured_at = measured, stamp
        storage.save_player_latency(entry)

    probe = AutoLatencyProbe(config, None, persist, clock=lambda: 0)
    for _ in range(4):
        probe.accept(-.2, 0)
    assert probe.current_delay_ms() == 0  # still slewing this session
    restored = Storage(tmp_path/'config.json').get_player_latency('room')
    restarted = AutoLatencyProbe(restored, None, persist, clock=lambda: 0)
    assert restarted.current_delay_ms() == -200  # remembered before any new sample
