"""Universal position sampling, estimation, migration and lifecycle contracts."""
import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from lampastream.latency import AutoLatencyProbe, FollowPositionContext
from lampastream.lms_follower import LmsFollower, LmsSyncGroupObserver
from lampastream.migration import migrate_file
from lampastream.models import PlayerLatency, Profile
from lampastream.player_manager import ActiveSession, PlayerManager
from lampastream.schema import empty_config
from lampastream.storage import Storage

OWN = '02:00:00:00:00:01'
FOLLOW = '02:00:00:00:00:02'


def fixture_probe(**fields):
    follower = LmsFollower('127.0.0.1', FOLLOW, OWN)
    context = [FollowPositionContext(True, True, True, 1, 1, 0)]
    follower.latency_context = lambda: context[0]
    follower.realign_own_player = Mock()
    now = [5.0]
    saved = []
    probe = AutoLatencyProbe(PlayerLatency(FOLLOW, strategy='auto', **fields), follower,
                             lambda delay, stamp: saved.append((delay, stamp)),
                             clock=lambda: now[0])
    return probe, follower, context, now, saved


def test_median_outlier_precision_and_window():
    probe, _, _, _, saved = fixture_probe()
    probe.player_delay = 0
    for value in [1.00, 1.02, .98, 1.01, 1.03, .99, 1.00]:
        assert probe.accept(value, 5)
    assert probe.current_delay_ms() == 1000
    assert probe.precision_ms() == 15
    assert not probe.accept(2.00, 8)  # observed whole-second bridge correction
    assert len(probe.samples) == 7
    assert probe.accept(1.01, 11)
    assert len(probe.samples) == 7
    assert saved[-1][0] == 1010


def test_first_estimate_then_fifty_ms_limit_and_arithmetic():
    probe, _, _, _, _ = fixture_probe(trim_ms=-100, measured_delay_ms=500)
    probe.player_delay = 200
    assert probe.current_delay_ms() == 400
    for value in [1, 1.01]:
        probe.accept(value, 5)
        assert probe.current_delay_ms() == 400
    probe.accept(.99, 11)
    assert probe.current_delay_ms() == 1100
    for value in [1.3] * 7:
        old = probe.current_delay_ms()
        probe.accept(value, 14)
        assert abs(probe.current_delay_ms() - old) <= 50
    assert probe.current_delay_ms() == 1360
    probe.accept(1.3, 17)
    assert probe.current_delay_ms() == 1400


def test_disagreeing_first_samples_do_not_jump_and_negative_clamps():
    probe, _, _, _, _ = fixture_probe(trim_ms=-1000)
    for value in [.1, .35, .49]:
        probe.accept(value, 5)
    assert probe.first
    for value in [.3, .3, .3]:
        probe.accept(value, 5)
    assert not probe.first
    assert probe.current_delay_ms() == 0


@pytest.mark.parametrize('connected,playing,same', [(False, True, True),
                                                    (True, False, True), (True, True, False)])
def test_ineligible_players_never_query(connected, playing, same):
    probe, _, contexts, now, _ = fixture_probe()
    contexts[0] = replace(contexts[0], connected=connected, playing=playing, same_track=same)
    probe._value = Mock(side_effect=AssertionError('must not query'))
    now[0] = 99
    asyncio.run(probe.tick())
    assert probe.state == 'idle'


def test_burst_steady_guard_and_preference_once():
    async def run():
        probe, _, contexts, now, _ = fixture_probe()
        calls = []
        def value(mac, command):
            calls.append((now[0], mac, command))
            return (100 if command.startswith('playerpref') else now[0] + (1 if mac == OWN else 0),
                    now[0])
        probe._value = value
        for second in range(61):
            now[0] = second
            await probe.tick()
        own_times = [t for t, mac, cmd in calls if mac == OWN and cmd == 'time ?']
        assert own_times == list(range(5, 36, 3)) + [50]
        assert sum(cmd.startswith('playerpref') for _, _, cmd in calls) == 1
        assert probe.current_delay_ms() == 1100
        contexts[0] = replace(contexts[0], transition=2, changed_at=60)
        for second in range(61, 65):
            now[0] = second
            previous = len(calls)
            await probe.tick()
            assert len(calls) == previous
        now[0] = 65
        await probe.tick()
        assert calls[-1][0] == 65
    asyncio.run(run())


def test_order_and_monotonic_midpoint_correction():
    probe, _, _, now, _ = fixture_probe()
    orders = []
    def value(mac, command):
        now[0] += .1
        orders.append(mac)
        return (now[0] + (1 if mac == OWN else 0), now[0])
    probe._value = value
    assert probe._pair() == pytest.approx(1)
    probe.order = True
    assert probe._pair() == pytest.approx(1)
    assert orders == [OWN, FOLLOW, FOLLOW, OWN]


def test_transition_during_pair_discards_sample():
    async def run():
        probe, _, contexts, _, _ = fixture_probe()
        probe.cache[FOLLOW] = 0
        def pair():
            contexts[0] = replace(contexts[0], transition=2)
            return 1
        probe._pair = pair
        await probe.tick()
        assert not probe.samples
    asyncio.run(run())


def test_negative_residual_realigns_only_once_per_track():
    async def run():
        probe, follower, contexts, now, _ = fixture_probe()
        probe.cache[FOLLOW] = 0
        probe._pair = lambda: -.5
        for second in range(5, 81):
            now[0] = second
            await probe.tick()
        follower.realign_own_player.assert_called_once_with(1)
        assert probe.current_delay_ms() == 0
        contexts[0] = replace(contexts[0], track=2, transition=2, changed_at=81)
        for second in range(81, 130):
            now[0] = second
            await probe.tick()
        assert follower.realign_own_player.call_count == 2
    asyncio.run(run())


def test_fake_cli_only_positions_and_one_preference_no_paused_or_stopped_requests():
    async def run():
        commands = []
        async def handle(reader, writer):
            line = (await reader.readline()).decode().strip()
            commands.append(line)
            value = 125 if 'playerpref' in line else 101 if line.startswith(OWN) else 100
            writer.write((line.removesuffix('?') + str(value) + '\n').encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        try:
            probe, follower, contexts, now, _ = fixture_probe()
            follower._port = server.sockets[0].getsockname()[1]
            for second in (5, 8, 11):
                now[0] = second
                await probe.tick()
            followed = [c for c in commands if c.startswith(FOLLOW)]
            assert followed.count(f'{FOLLOW} playerpref playDelay ?') == 1
            assert followed.count(f'{FOLLOW} time ?') == 3
            assert all(c in {f'{FOLLOW} time ?', f'{FOLLOW} playerpref playDelay ?'}
                       for c in followed)
            for mode in ('pause', 'stop'):
                follower._transport_mode = mode
                contexts[0] = replace(contexts[0], playing=False, transition=2)
                previous = list(commands)
                now[0] += 100
                await probe.tick()
                assert commands == previous
            assert probe.current_delay_ms() == 1125
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_migration_backup_upnp_and_persistence_start_value(tmp_path):
    data = empty_config()
    data['player_latencies'] = [dict(player_mac=FOLLOW, strategy='upnp', fixed_delay_ms=321,
                                     speaker_ip='192.0.2.1')]
    path = tmp_path / 'config.json'
    original = json.dumps(data).encode()
    path.write_bytes(original)
    assert migrate_file(path)
    assert next(tmp_path.glob('*.bak')).read_bytes() == original
    storage = Storage(path)
    config = storage.get_player_latency(FOLLOW)
    assert config.strategy == 'fixed' and config.fixed_delay_ms == 321
    assert 'speaker_ip' not in config.to_dict()
    assert not migrate_file(path)
    config.strategy = 'auto'
    config.trim_ms = 50
    config.measured_delay_ms = 1200
    config.measured_at = 123456.0
    storage.save_player_latency(config)
    loaded = Storage(path).get_player_latency(FOLLOW)
    probe = AutoLatencyProbe(loaded, None, Mock())
    assert probe.current_delay_ms() == 1250
    assert loaded.measured_at == 123456.0


def test_sync_group_fallback_and_readonly_status(tmp_path):
    async def run():
        storage = Storage(tmp_path / 'config.json')
        config = PlayerLatency(FOLLOW, strategy='auto', fixed_delay_ms=456, trim_ms=100)
        storage.save_player_latency(config)
        manager = PlayerManager(storage)
        session = ActiveSession(Profile(player_mac=OWN))
        session.follower = LmsSyncGroupObserver('host', OWN, lambda: [], Mock())
        manager._active = session
        await manager._apply_probe_for_master(session, FOLLOW)
        assert session.probe.current_delay_ms() == 456
        status = manager.latency_status(config)
        assert status['strategy'] == 'fixed'
        assert status['state'] == 'not measurable (sync group)'
        assert 'shared group position' in status['reason']
        await session.probe.stop()
    asyncio.run(run())


def test_preference_absence_is_cached_and_lowering_is_bounded():
    async def run():
        probe, _, _, now, _ = fixture_probe()
        queries = []
        def value(mac, command):
            queries.append(command)
            if command.startswith('playerpref'):
                raise ValueError('unsupported')
            return (now[0] + (1 if mac == OWN else 0), now[0])
        probe._value = value
        for second in (5, 8, 11):
            now[0] = second
            await probe.tick()
        assert queries.count('playerpref playDelay ?') == 1
        assert probe.delay == 1000
        for _ in range(7):
            previous = probe.delay
            probe.accept(.7, 15)
            assert -50 <= probe.delay - previous <= 0
    asyncio.run(run())


def test_stop_owns_inflight_socket_worker_and_never_applies_retired_sample():
    import threading
    async def run():
        probe, _, _, _, saved = fixture_probe()
        probe.cache[FOLLOW] = 0
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        def pair():
            entered.set()
            assert release.wait(2)
            finished.set()
            return 1
        probe._pair = pair
        await probe.start()
        assert await asyncio.to_thread(entered.wait, 1)
        stop = asyncio.create_task(probe.stop())
        await asyncio.sleep(.01)
        assert not stop.done()
        release.set()
        await stop
        assert finished.is_set()
        assert not saved and not probe.samples
    asyncio.run(run())


def test_query_pair_aborts_before_followed_request_on_pause():
    probe, _, contexts, _, _ = fixture_probe()
    calls = []
    def value(mac, command):
        calls.append(mac)
        contexts[0] = replace(contexts[0], playing=False, transition=2)
        return 100, 5
    probe._value = value
    with pytest.raises(ValueError, match='Playback changed'):
        probe._pair()
    assert calls == [OWN]


@pytest.mark.parametrize('event', ['playlist newsong', 'time 42', 'pause 1', 'pause 0', 'stop'])
@pytest.mark.parametrize('mac', [OWN, FOLLOW])
def test_either_player_transition_updates_measurement_guard(event, mac):
    follower = LmsFollower('host', FOLLOW, OWN)
    follower._get_current_url = Mock(return_value='url')
    follower._mirror_track = Mock()
    follower._send_pause = Mock()
    follower._send_stop = Mock()
    follower.realign_own_player = Mock()
    previous = follower.latency_context()
    asyncio.run(follower._handle_line(f'{mac} {event}'))
    current = follower.latency_context()
    assert current.transition > previous.transition
    assert current.changed_at >= previous.changed_at
    if event == 'playlist newsong':
        assert current.track == previous.track + int(mac == FOLLOW)


def test_auto_alignment_once_survives_probe_refresh_but_explicit_seek_is_relayed():
    follower = LmsFollower('host', FOLLOW, OWN)
    follower._connected = True
    follower._transport_mode = follower._own_mode = 'play'
    follower._own_url = follower._mirrored_url = 'url'
    follower._align_seed_position = Mock()
    follower.realign_own_player(0)
    follower.realign_own_player(0)
    assert follower._align_seed_position.call_count == 1
    follower.realign_own_player(0, False)
    assert follower._align_seed_position.call_count == 2


def test_trim_refresh_preserves_estimate_and_first_step_allowance(tmp_path):
    async def run():
        storage = Storage(tmp_path / 'config.json')
        config = PlayerLatency(FOLLOW, strategy='auto')
        storage.save_player_latency(config)
        manager = PlayerManager(storage)
        probe, follower, _, _, _ = fixture_probe()
        for residual in (1, 1, 1):
            probe.accept(residual, 5)
        session = ActiveSession(Profile(player_mac=OWN))
        session.follower = follower
        session.probe = probe
        session.latency_mac = FOLLOW
        config.trim_ms = 1000
        storage.save_player_latency(config)
        await manager._apply_probe_for_master(session, FOLLOW)
        assert session.probe is probe
        assert not probe.first and len(probe.samples) == 3
        assert probe.current_delay_ms() == 1000
        probe.accept(1, 8)
        assert probe.current_delay_ms() == 1050
    asyncio.run(run())


def test_inactive_entry_has_zero_applied_delay_but_keeps_saved_start_value(tmp_path):
    config = PlayerLatency(FOLLOW, strategy='auto', measured_delay_ms=900, trim_ms=100)
    manager = PlayerManager(Storage(tmp_path / 'config.json'))
    status = manager.latency_status(config)
    assert status['state'] == 'idle'
    assert status['applied_delay_ms'] == 0
    assert AutoLatencyProbe(config, None, Mock()).current_delay_ms() == 1000


def test_recent_samples_are_bounded_timestamped_and_detached(monkeypatch):
    probe, _, context, _, _ = fixture_probe()
    clock = iter(range(100, 111))
    monkeypatch.setattr('lampastream.latency.time.time', lambda: next(clock))
    for i in range(10):
        assert probe.accept(1 + i / 1000, i)
    before = probe.status()['samples']
    assert len(before) == 7
    assert before[0] == {'residual_ms': 1003, 'timestamp': 103}
    assert before[-1] == {'residual_ms': 1009, 'timestamp': 109}
    assert not probe.accept(9, 11)
    assert probe.status()['samples'] == before
    before[0]['residual_ms'] = 99999
    assert probe.status()['samples'][0]['residual_ms'] == 1003
    probe.eligible(context[0], 5)
    assert probe.status()['samples'] == []
