"""Release ownership, clocks, REST and API tests without physical bridges."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lampastream.api import router
from lampastream.hue_output import HueDriver, HueOutputConfig
from lampastream.hue_release import HueReleaseRest
from lampastream.migration import convert
from lampastream.models import BridgeConfig, Coupling
from lampastream.schema import empty_config
from lampastream.storage import Storage
from lampastream.track_position import TrackPosition


class Session:
    def __init__(self, *args, **kwargs):
        self.is_streaming = False
        self.remote = ('active', 'ours')
        self.starts = []
        self.stop = AsyncMock(side_effect=self.stopped)
        self.aclose = AsyncMock()
        self.send = Mock()

    def stopped(self):
        self.is_streaming = False

    async def start(self, area, *, stop_others):
        self.starts.append(stop_others)
        self.is_streaming = True
        self.remote = ('active', 'ours')

    async def remote_status(self):
        return self.remote


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', Session)
    result = HueDriver(HueOutputConfig(BridgeConfig(), 'area', 'Room'), [])
    result._rest = SimpleNamespace(capture=AsyncMock(), finish=AsyncMock(), stop_area=AsyncMock(),
                                   available=AsyncMock(return_value=True))
    result._clock = lambda: result.now
    result.now = 0
    result._last_audio = 0
    return result


async def started(driver):
    await driver.start()
    driver._health_task.cancel()
    driver._remote_task.cancel()
    await asyncio.gather(driver._health_task, driver._remote_task, return_exceptions=True)
    driver._health_task = driver._remote_task = None
    return driver._session


@pytest.mark.anyio
@pytest.mark.parametrize('remote', [('inactive', ''), ('active', 'someone-else')])
async def test_external_release_does_not_reconnect_and_logs_once(driver, remote, caplog):
    caplog.set_level('INFO')
    session = await started(driver)
    session.remote = remote
    await driver._check_remote()
    await driver._check_remote()
    assert driver.output_status['state'] == 'released'
    assert driver.output_status['release_kind'] == 'external'
    assert session.starts == [True]
    assert driver._recovery_task is None
    assert session._area_id is None  # local-only teardown prevents stopping new owner
    driver._rest.finish.assert_awaited_once_with('restore', external=True)
    assert caplog.text.count('Light output released:') == 1
    driver.observe_audio(2)
    await driver._local_tick()
    assert session.starts == [True]  # continuing music cannot undo an external stop
    await driver.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['pause', 'stop', 'no frames'])
async def test_idle_30_seconds_resume_and_busy_bridge(driver, transport):
    session = await started(driver)
    if transport != 'no frames':
        driver.transport = lambda: TrackPosition(title='Song', playing=False)
    await driver._local_tick()
    driver.now = 29
    await driver._local_tick()
    assert driver.output_status['state'] == 'streaming'
    driver.now = 30
    await driver._local_tick()
    assert driver.output_status == {'state': 'released', 'reason': 'Released while idle',
                                    'release_kind': 'idle'}
    generation = driver.output_generation
    driver._rest.available.return_value = False
    driver.transport = lambda: TrackPosition(title='Song', playing=True)
    driver.observe_audio(1)
    await driver._local_tick()
    assert driver.output_status['reason'] == 'Another controller is using the lights'
    assert session.starts == [True]
    driver._rest.available.return_value = True
    await driver._local_tick()
    assert session.starts == [True, False]
    assert driver.output_generation > generation
    assert driver.output_status['state'] == 'streaming'
    await driver.aclose()


@pytest.mark.anyio
async def test_zero_never_idle_releases_and_explicit_take_may_stop_others(driver):
    session = await started(driver)
    driver._config.release_after_idle_s = 0
    driver.now = 100000
    await driver._local_tick()
    assert driver.output_status['state'] == 'streaming'
    await driver.release('Stopped from the Hue app or another controller', external=True)
    driver._rest.available.return_value = False
    await driver.take_lights(explicit=True)
    assert session.starts == [True, True]
    driver._rest.available.assert_not_awaited()
    await driver.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['restore', 'off', 'leave'])
@pytest.mark.parametrize('action', ['idle', 'external', 'stop'])
async def test_each_release_policy_and_stop_is_idempotent(driver, mode, action):
    driver._config.on_release = mode
    await started(driver)
    if action == 'stop':
        await driver.stop()
    else:
        await driver.release(action, idle=action == 'idle', external=action == 'external')
    driver._rest.finish.assert_awaited_once_with(mode, external=action == 'external')
    await driver.aclose()
    assert driver._rest.finish.await_count == 1


@pytest.mark.anyio
async def test_recent_local_failure_recovers_without_stop_others(driver):
    session = await started(driver)
    driver._local_failure_at = 1
    driver.now = 15
    session.remote = ('inactive', '')
    driver._sleep = AsyncMock()
    await driver._check_remote()
    await driver._recovery_task
    assert session.starts == [True, False]
    # Remote checks must not extend the local-failure window.
    assert driver._local_failure_at == 1
    driver.now = 17
    session.remote = ('inactive', '')
    await driver._check_remote()
    assert driver.output_status['state'] == 'released'
    await driver.aclose()


@pytest.mark.anyio
async def test_real_library_external_disconnect_never_calls_bridge_stop(monkeypatch):
    from hue_entertainment import EntertainmentSession
    session = EntertainmentSession('bridge', 'key', 'client', idle_timeout=0)
    session._area_id = 'area'
    session._streamer._connected = True
    session._streamer.disconnect = Mock(side_effect=lambda: setattr(
        session._streamer, '_connected', False))
    session._api.stop_entertainment = AsyncMock()
    session._api.close = AsyncMock()
    d = HueDriver(HueOutputConfig(BridgeConfig(), 'area', 'Room'), [])
    d._session = session
    await d._disconnect(external=True)
    await session.aclose()
    session._api.stop_entertainment.assert_not_awaited()
    session._streamer.disconnect.assert_called_once()


def resources():
    return [
        {'id': 'area', 'type': 'entertainment_configuration', 'channels': [
            {'members': [{'service': {'rid': 'ent', 'rtype': 'entertainment'}}]}],
         'light_services': [{'rid': 'light2', 'rtype': 'light'}]},
        {'id': 'ent', 'type': 'entertainment', 'owner': {'rid': 'device'}},
        {'id': 'device', 'type': 'device', 'services': [{'rid': 'light1', 'rtype': 'light'}]},
        {'id': 'light1', 'type': 'light', 'on': {'on': True}, 'dimming': {'brightness': 42},
         'color': {'xy': {'x': .3, 'y': .4}},
         'color_temperature': {'mirek': None, 'mirek_valid': False}},
        {'id': 'light2', 'type': 'light', 'on': {'on': False},
         'color_temperature': {'mirek': 300, 'mirek_valid': True}},
    ]


@pytest.mark.anyio
@pytest.mark.parametrize('mode,external,writes', [
    ('restore', False, 2), ('restore', True, 2), ('off', False, 2),
    ('off', True, 0), ('leave', False, 0), ('leave', True, 0)])
async def test_rest_snapshot_and_release_writes(mode, external, writes):
    rest = HueReleaseRest(BridgeConfig(), 'area')
    rest._request = AsyncMock(return_value=resources())
    await rest.capture()
    assert rest.snapshot['light1']['color'] == {'xy': {'x': .3, 'y': .4}}
    assert rest.snapshot['light2']['color_temperature'] == {'mirek': 300}
    rest._request.reset_mock()
    await rest.finish(mode, external=external)
    assert rest._request.await_count == writes
    if writes:
        for args in rest._request.await_args_list:
            assert args.args[0] == 'PUT'
            assert args.args[2] == (rest.snapshot[args.args[1].split('/')[-1]]
                                    if mode == 'restore' else {'on': {'on': False}})


@pytest.mark.anyio
async def test_snapshot_failure_and_rest_timeouts_are_bounded_and_warn(caplog):
    rest = HueReleaseRest(BridgeConfig(), 'area')
    rest._request = AsyncMock(side_effect=TimeoutError)
    await rest.capture()
    await rest.finish('restore')
    assert rest.snapshot is None
    assert 'snapshot unavailable' in caplog.text
    rest.snapshot, rest.light_ids = {'light': {'on': {'on': True}}}, ['light']
    await rest.finish('restore')
    assert 'within its budget' in caplog.text


@pytest.mark.anyio
async def test_all_areas_availability_includes_other_controller():
    rest = HueReleaseRest(BridgeConfig(), 'area')
    rest._request = AsyncMock(return_value=[{'id': 'other-area', 'status': 'active'}])
    assert not await rest.available()


@pytest.mark.parametrize('value', [-1, 3601, 'bad', 1.5, True, None])
def test_invalid_idle_falls_back_with_warning(value, caplog):
    assert Coupling(release_after_idle_s=value).release_after_idle_s == 30
    assert 'using 30 seconds' in caplog.text


def test_additive_config_migration_is_idempotent():
    original = empty_config()
    original['couplings'] = [{'id': 'c', 'name': 'Room'}]
    result = convert(original)
    assert result['couplings'][0]['release_after_idle_s'] == 30
    assert result['couplings'][0]['on_release'] == 'restore'
    assert convert(result) == result
    assert 'release_after_idle_s' not in original['couplings'][0]


def test_api_validation_and_take_lights(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.storage = Storage(tmp_path / 'config.json')
    coupling = Coupling(name='Room')
    app.state.storage.save_coupling(coupling)
    driver = SimpleNamespace(take_lights=AsyncMock(), release=AsyncMock(),
                             _config=SimpleNamespace())
    app.state.player_manager = Mock(active_coupling_id=coupling.id, output_status={
        'state': 'streaming', 'reason': None}, _active=SimpleNamespace(hue_driver=driver))
    with TestClient(app) as client:
        url = f'/api/couplings/{coupling.id}'
        assert client.patch(url, json={'release_after_idle_s': 0, 'on_release': 'off'}).json()[
            'release_after_idle_s'] == 0
        assert client.patch(url, json={'release_after_idle_s': 3601}).json()[
            'release_after_idle_s'] == 30
        assert client.patch(url, json={'on_release': 'invalid'}).status_code == 422
        assert client.post(url + '/take-lights').status_code == 200
        driver.take_lights.assert_awaited_once_with(explicit=True)
        assert client.post(url + '/release-lights').status_code == 200
        driver.release.assert_awaited_once_with('You released the lights', explicit=True)
        app.state.player_manager.active_coupling_id = None
        assert client.post(url + '/take-lights').status_code == 409
        assert client.post(url + '/release-lights').status_code == 409


@pytest.mark.anyio
async def test_hanging_rest_request_has_three_second_deadline(monkeypatch):
    import httpx
    real_wait = asyncio.wait_for
    seen = []

    async def short_wait(coro, timeout):
        seen.append(timeout)
        return await real_wait(coro, .01)

    async def hang(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr('lampastream.hue_release.asyncio.wait_for', short_wait)
    monkeypatch.setattr(httpx.AsyncClient, 'request', hang)
    rest = HueReleaseRest(BridgeConfig(host='unused'), 'area')
    await rest.capture()
    assert seen == [3]
    assert rest.snapshot is None


@pytest.mark.anyio
async def test_total_rest_budget_stops_many_slow_lights(monkeypatch, caplog):
    real_timeout = asyncio.timeout
    budgets = []

    def short_timeout(seconds):
        budgets.append(seconds)
        return real_timeout(.02)

    async def slow(*args):
        await asyncio.sleep(.01)

    monkeypatch.setattr('lampastream.hue_release.asyncio.timeout', short_timeout)
    rest = HueReleaseRest(BridgeConfig(), 'area')
    rest.light_ids = [str(i) for i in range(100)]
    rest.snapshot = {i: {'on': {'on': True}} for i in rest.light_ids}
    rest._request = slow
    await rest.finish('restore')
    assert budgets == [10]
    assert 'within its budget' in caplog.text


def test_early_tap_release_discards_old_scenes_and_keeps_tap_generation(monkeypatch):
    from lampastream.airplay_timing import AirPlayAutoLatencyProbe, TimingDiagnostics
    from lampastream.models import PlayerLatency, Profile
    from lampastream.sync_engine import CanonicalAnalysisPipeline, SyncEngine
    from lampastream.types import AudioFeatures

    clock = [10.1]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    diagnostics.tap_source, diagnostics.tap_generation = 'early tap', 1
    diagnostics.tap_arrival(.5, 0)

    def features(target):
        return AudioFeatures(bars=[.3] * 30, bass=.3, mid=.3, full=.3, centroid=.3,
                             onset=False, onset_strength=0, play_monotonic=target,
                             received_monotonic=10, timing_generation=1)

    class Pipeline(CanonicalAnalysisPipeline):
        def __init__(self):
            self.records = [SimpleNamespace(features=features(10.5))]
            self.seq = 1

        @property
        def pub_seq(self):
            return self.seq

        def drain_publications(self):
            records, self.records = self.records, []
            return records

    async def run():
        pipeline = Pipeline()
        output = SimpleNamespace(output_generation=0, accepting_frames=True,
                                 observe_audio=Mock(), send=Mock())
        probe = AirPlayAutoLatencyProbe(PlayerLatency(player_mac='ap', strategy='auto'),
                                       diagnostics, 0, Mock())
        engine = SyncEngine(None, Profile(), analyser=pipeline, probe=probe, timing=diagnostics)
        engine._effect = SimpleNamespace(render=lambda f, t: f.play_monotonic, mix=0)

        async def tick(dt):
            clock[0] += dt
            if 10.12 <= clock[0] < 10.3:
                output.accepting_frames = False
                output.output_generation = 1
            elif clock[0] >= 10.3 and output.output_generation == 1:
                output.accepting_frames = True
                output.output_generation = 2
            elif 10.4 <= clock[0] < 10.44:
                pipeline.records.append(SimpleNamespace(features=features(10.7)))
                pipeline.seq += 1
            if clock[0] > 10.8:
                raise asyncio.CancelledError

        monkeypatch.setattr('lampastream.sync_engine.time',
                            SimpleNamespace(monotonic=lambda: clock[0]))
        monkeypatch.setattr('lampastream.sync_engine.asyncio', SimpleNamespace(sleep=tick))
        with pytest.raises(asyncio.CancelledError):
            await engine.run(output)
        assert diagnostics.tap_generation == 1
        assert output.send.call_count == 1
        assert output.send.call_args.args[0] == 10.7
        assert output.send.call_args.args[1] >= 10.7
    asyncio.run(run())


@pytest.mark.anyio
async def test_busy_controller_does_not_cause_late_reacquisition_without_music(driver):
    session = await started(driver)
    driver.now = 30
    await driver._local_tick()
    driver._rest.available.return_value = False
    driver.observe_audio(1)
    await driver._local_tick()
    driver.now = 100
    driver._rest.available.return_value = True
    await driver._local_tick()
    assert session.starts == [True]
    assert driver.output_status['state'] == 'released'
    await driver.aclose()


@pytest.mark.anyio
async def test_remote_stop_during_take_does_not_deadlock(driver):
    session = await started(driver)
    await driver.release('Released while idle', idle=True)
    original = session.start

    async def start_then_external_stop(*args, **kwargs):
        await original(*args, **kwargs)
        session.remote = ('inactive', '')

    session.start = start_then_external_stop
    await asyncio.wait_for(driver.take_lights(explicit=True), 1)
    assert driver.output_status['state'] == 'released'
    assert driver._recovery_task is None
    await driver.aclose()


@pytest.mark.anyio
async def test_cleanup_failure_still_finishes_release_and_shutdown(driver, caplog):
    session = await started(driver)
    session.stop.side_effect = OSError('closed')
    await driver.stop()
    assert driver.output_status['state'] == 'released'
    driver._rest.finish.assert_awaited_once_with('restore', external=False)
    assert 'cleanup failed' in caplog.text
    await driver.aclose()


@pytest.mark.anyio
async def test_idle_deadline_checks_for_takeover_before_area_stop(driver):
    session = await started(driver)
    driver._config.on_release = 'off'
    session.remote = ('active', 'another-controller')
    driver.now = 30
    await driver._local_tick()
    assert driver.output_status['reason'] == 'Stopped from the Hue app or another controller'
    driver._rest.stop_area.assert_not_awaited()
    driver._rest.finish.assert_awaited_once_with('off', external=True)
    await driver.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['restore', 'off', 'leave'])
@pytest.mark.parametrize('state', ['streaming', 'reconnecting', 'failed'])
async def test_explicit_release_cancels_recovery_and_stays_released(driver, mode, state):
    driver._config.on_release = mode
    session = await started(driver)
    driver._state = state
    driver._recovery_task = asyncio.create_task(asyncio.sleep(100))
    await driver.release('You released the lights', explicit=True)
    assert driver._recovery_task.cancelled()
    assert driver.output_status == {'state': 'released', 'reason': 'You released the lights',
                                    'release_kind': 'explicit'}
    driver._rest.finish.assert_awaited_once_with(mode, external=False)
    session.stop.assert_awaited_once()
    for title in ['Original', 'New track']:
        driver.transport = lambda title=title: TrackPosition(title=title, playing=True)
        driver.observe_audio(title)
        await driver._local_tick()
    assert session.starts == [True]
    await driver.release('You released the lights', explicit=True)
    session.stop.assert_awaited_once()
    driver._rest.finish.assert_awaited_once()
    await driver.take_lights(explicit=True)
    assert session.starts == [True, True]
    assert 'release_kind' not in driver.output_status
    await driver.aclose()
