"""Session readiness and timing diagnostics, with no bridge or live LMS."""
import asyncio
from unittest.mock import Mock

import pytest

from lampastream.lms_follower import LmsSyncGroupObserver
from lampastream.lms_timing import LmsHeadStart, LmsTimedSource, LmsTimingDiagnostics, WriteClock
from lampastream.models import VirtualPlayer


class Cli:
    def __init__(self, now):
        self.now = now
        self.connected = False
        self.pref = 0
        self.read_failures = 0
        self.calls = []

    async def __call__(self, host, command):
        self.calls.append((self.now[0], command))
        prefix = 'virtual '
        if command == prefix + 'connected ?\n':
            return prefix + f'connected {int(self.connected)}'
        if command == prefix + 'playerpref playDelay 500\n':
            self.pref = 500
            return 'ok'
        if command == prefix + 'playerpref playDelay ?\n':
            if self.read_failures:
                self.read_failures -= 1
                return ''
            return prefix + f'playerpref playDelay {self.pref}'
        if command == prefix + 'playerpref startDelay ?\n':
            return prefix + 'playerpref startDelay 0'
        raise AssertionError(command)


def setup():
    now = [0.0]
    player = VirtualPlayer(player_mac='virtual', follow_mode='sync_group')
    source = LmsTimedSource(Mock(), player, clock=lambda: now[0], ready=False)
    cli = Cli(now)
    return now, source, cli, LmsHeadStart(player, source, cli, lambda: now[0])


def test_registration_group_reconnect_pref_loss_and_leave():
    async def exercise():
        now, source, cli, head = setup()
        assert not await head.refresh()
        assert source.readiness_state == 'waiting'
        assert not source.ready
        assert source.timing.tap_source == 'delay fallback'
        assert all('playerpref' not in command for _, command in cli.calls)
        now[0] = 12
        cli.connected = True
        assert await head.refresh()
        assert source.readiness_state == 'unsynced'
        assert source.reason == 'Not synced with a speaker yet: sync it in LMS'
        head.group_refresh(['speaker'])
        assert not source.ready  # must verify after group change
        assert await head.refresh()
        assert source.ready and source.timing.tap_source == 'LMS head start'
        generation = source.timing.tap_generation
        cli.connected = False
        assert not await head.refresh()
        assert not source.ready and source.timing.tap_generation > generation
        cli.connected = True
        cli.pref = 0
        head.group_refresh(['speaker'], True)
        assert await head.refresh()
        assert cli.pref == 500 and source.ready
        cli.pref = 0
        with pytest.raises(ValueError):
            await head.refresh()
        # run() handles this error by dropping readiness and retrying.
        head.verified = False
        source.set_readiness(False, 'fallback', 'retrying')
        assert await head.refresh()
        assert source.ready
        head.group_refresh([])
        assert not source.ready
        assert await head.refresh()
        assert source.readiness_state == 'unsynced'
        assert not any('startDelay 0' in command for _, command in cli.calls)
    asyncio.run(exercise())


def test_retry_backoff_has_no_permanent_fallback():
    async def exercise():
        now, source, cli, head = setup()
        cli.connected = True
        cli.read_failures = 5
        head.group_refresh(['speaker'])
        delays = []

        async def wait(seconds=None):
            if seconds is None:
                assert source.ready
                raise asyncio.CancelledError
            delays.append(seconds)
            now[0] += seconds
        head.wait = wait
        with pytest.raises(asyncio.CancelledError):
            await head.run()
        assert delays == [1, 2, 5, 10, 30]
        assert source.ready
        sets = [(t, c) for t, c in cli.calls if c.endswith('playDelay 500\n')]
        assert [t for t, _ in sets] == [0, 1, 3, 8, 18, 48]
    asyncio.run(exercise())


@pytest.mark.parametrize('registered_after,expected', [
    (3, [0, 1]), (12, [0, 1, 3, 8]), (60, [0, 1, 3, 8, 18, 30]),
])
def test_connection_poll_window_then_continued_retry(registered_after, expected):
    async def exercise():
        now, source, cli, head = setup()
        times = []

        async def wait(seconds=None):
            if seconds is None:
                assert head.verified and not source.ready
                raise asyncio.CancelledError
            times.append(now[0])
            now[0] += seconds
            if now[0] >= registered_after:
                cli.connected = True
        head.wait = wait
        with pytest.raises(asyncio.CancelledError):
            await head.run()
        assert times == expected
        assert head.verified and source.readiness_state == 'unsynced'
    asyncio.run(exercise())


def test_stop_cancels_an_inflight_cli_immediately():
    async def exercise():
        _, source, _, head = setup()
        entered = asyncio.Event()
        closed = asyncio.Event()

        async def exchange(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        head.exchange = exchange
        task = asyncio.create_task(head.run())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, .1)
        assert closed.is_set() and not source.ready
    asyncio.run(exercise())


def test_global_and_player_client_notifications_request_reverification():
    async def exercise():
        observer = LmsSyncGroupObserver('unused', 'virtual', lambda: [], Mock())
        for line in ['client new virtual', 'virtual client reconnect',
                     'client disconnect virtual', 'virtual sync speaker']:
            observer._reconnected = False
            observer._refresh_requested.clear()
            await observer._handle_line(line)
            assert observer._reconnected and observer._refresh_requested.is_set()
    asyncio.run(exercise())


def test_write_clock_fit_publishes_interval_residual_statistics():
    fit = WriteClock()
    for i in range(100):
        fit.observe(i * 441, i * .01, i * .01 + .001, 44100, 1, 0, True)
    points = list(fit.samples)
    assert len(points) == 99
    residuals = [max(lo - fit.at(pos), fit.at(pos) - hi, 0) * 1000 for pos, lo, hi in points]
    assert max(residuals) < 1


def test_each_scene_keeps_real_processing_provenance_without_cadence_gate():
    now = [1.030]
    diagnostics = LmsTimingDiagnostics(clock=lambda: now[0])
    diagnostics.scene_ready(1, 1.019, 1.5)
    diagnostics.scene_ready(1.001, 1.020, 1.501)
    now[0] = 1.502
    diagnostics.processing(1, 1.019, 1.5)
    data = diagnostics.snapshot()
    assert data['median_processing_ms'] == pytest.approx(21)
    events = data['events']
    assert len([event for event in events if event['kind'] == 'scene-ready']) == 2
    event = events[-1]
    assert (event['received_monotonic'], event['ready_monotonic'], event['sent_monotonic']) == (
        1, 1.019, 1.5)
    assert event['delay_hold_ms'] == pytest.approx(481)


def test_preference_lost_while_healthy_disables_then_retries():
    async def exercise():
        now, source, cli, head = setup()
        cli.connected = True
        head.group_refresh(['speaker'])
        healthy = 0

        async def wait(seconds=None):
            nonlocal healthy
            if seconds is None:
                healthy += 1
                if healthy == 1:
                    cli.pref = 0
                    return
                assert source.ready
                raise asyncio.CancelledError
            assert not source.ready and source.timing.tap_source == 'delay fallback'
            assert seconds == 1
            now[0] += seconds
        head.wait = wait
        with pytest.raises(asyncio.CancelledError):
            await head.run()
        assert healthy == 2 and cli.pref == 500
        assert len([c for _, c in cli.calls if c.endswith('playDelay 500\n')]) == 2
    asyncio.run(exercise())


def test_existing_observer_peers_drive_even_same_target_group_changes(monkeypatch):
    from unittest.mock import AsyncMock

    import lampastream.lms_status as lms_status

    async def exercise():
        _, source, cli, head = setup()
        cli.connected = True
        target = AsyncMock()
        observer = LmsSyncGroupObserver('unused', 'virtual', lambda: ['virtual'], target,
                                        on_group_refresh=head.group_refresh)
        for peers in [[], ['speaker'], ['speaker', 'other'], []]:
            monkeypatch.setattr(lms_status, 'query_lms_sync_peers',
                                lambda *args, peers=peers: peers)
            await observer._refresh_group()
            assert await head.refresh()
            assert source.ready == bool(peers)
        assert target.await_count == 3  # Adding a peer preserves the selected speaker.
        assert len([c for _, c in cli.calls if c.endswith('playDelay 500\n')]) == 4
    asyncio.run(exercise())


def test_session_teardown_cancels_pending_registration_without_waiting(tmp_path):
    from lampastream.models import Profile
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    async def exercise():
        _, _, _, head = setup()
        entered = asyncio.Event()
        closed = asyncio.Event()

        async def exchange(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        head.exchange = exchange
        session = ActiveSession(Profile())
        session.head_start_task = asyncio.create_task(head.run())
        await entered.wait()
        manager = PlayerManager(Storage(tmp_path / 'config.json'))
        await asyncio.wait_for(manager._teardown_session(session), .1)
        assert closed.is_set()
        assert session.head_start_task is None
    asyncio.run(exercise())


def test_group_change_invalidates_before_target_reconciliation_finishes(monkeypatch):
    import lampastream.lms_status as lms_status

    async def exercise():
        _, source, cli, head = setup()
        cli.connected = True
        head.group_refresh(['old-speaker'])
        assert await head.refresh()
        entered = asyncio.Event()
        resume = asyncio.Event()

        async def target_changed(target):
            entered.set()
            await resume.wait()
        observer = LmsSyncGroupObserver('unused', 'virtual', lambda: [], target_changed,
                                        on_group_refresh=head.group_refresh)
        monkeypatch.setattr(lms_status, 'query_lms_sync_peers', lambda *args: ['new-speaker'])
        task = asyncio.create_task(observer._refresh_group())
        await entered.wait()
        assert not source.ready and head.group_pending
        resume.set()
        await task
        assert not head.group_pending and not source.ready
        assert await head.refresh()
        assert source.ready and head.peers == ('new-speaker',)
    asyncio.run(exercise())


def test_inflight_verification_cannot_commit_after_a_group_change():
    async def exercise():
        _, source, cli, head = setup()
        cli.connected = True
        head.group_refresh(['speaker'])
        entered = asyncio.Event()
        resume = asyncio.Event()

        async def exchange(host, command):
            if command.endswith('playerpref startDelay ?\n') and not entered.is_set():
                entered.set()
                await resume.wait()
            return await cli(host, command)
        head.exchange = exchange
        task = asyncio.create_task(head.refresh())
        await entered.wait()
        head.group_refresh(['new-speaker'])
        resume.set()
        assert await task is None
        assert not source.ready and head.dirty
        assert await head.refresh()
        assert source.ready
    asyncio.run(exercise())
