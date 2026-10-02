"""Tests for HueDriver (hue_output.py).

HueDriver talks to a real Hue bridge in production.  These tests use a
minimal stub session so no network or DTLS connection is required.
"""

from __future__ import annotations

from lampastream.hue_output import ChannelInfo, HueDriver, HueOutputConfig
from lampastream.models import BridgeConfig
from lampastream.types import Colour, Position, UniformScene

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _config() -> HueOutputConfig:
    bridge = BridgeConfig(name="Test bridge", host="192.168.1.2", app_key="k", client_key="c")
    return HueOutputConfig(bridge=bridge, area_id="area-1", area_name="Living room")


def _channels() -> list[ChannelInfo]:
    return [
        ChannelInfo(channel_id=0, position=Position(-1.0, 0.0, 0.0)),
        ChannelInfo(channel_id=1, position=Position(0.0, 0.0, 0.0)),
        ChannelInfo(channel_id=2, position=Position(1.0, 0.0, 0.0)),
    ]


class _FakeSession:
    """Records what HueDriver.send() passes to the underlying session."""

    def __init__(self) -> None:
        self.calls: list[list] = []

    def send(self, commands: list) -> None:
        self.calls.append(commands)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hue_driver_send_noop_before_start():
    """send() before start() (session=None) must not raise and last_colours stays empty."""
    driver = HueDriver(_config(), _channels())
    scene = UniformScene(Colour(1.0, 0.0, 0.0))
    driver.send(scene, 0.0)  # should be a silent no-op
    assert driver.last_colours == []


def test_hue_driver_send_updates_last_colours():
    """send() must store one Colour per channel in last_colours."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    scene = UniformScene(Colour(0.5, 0.3, 0.1))
    driver.send(scene, 0.0)

    assert len(driver.last_colours) == 3
    for colour in driver.last_colours:
        assert colour == Colour(0.5, 0.3, 0.1)


def test_hue_driver_send_calls_session_with_correct_channel_ids():
    """send() must produce one LightColorCommand per channel with the right channel_id."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    driver.send(UniformScene(Colour(1.0, 1.0, 1.0)), 0.0)

    assert len(fake.calls) == 1
    commands = fake.calls[0]
    assert len(commands) == 3
    ids = {c.channel_id for c in commands}
    assert ids == {0, 1, 2}


def test_hue_driver_send_converts_colour_to_16bit():
    """The LightColorCommands sent to the session must use 16-bit values."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    driver.send(UniformScene(Colour(1.0, 0.5, 0.0)), 0.0)

    commands = fake.calls[0]
    for cmd in commands:
        assert cmd.red == 65535
        assert cmd.green == 32767
        assert cmd.blue == 0


def test_hue_driver_last_colours_empty_on_new_instance():
    """A freshly constructed HueDriver must report an empty last_colours list."""
    driver = HueDriver(_config(), _channels())
    assert driver.last_colours == []


class LifecycleSession(_FakeSession):
    def __init__(self, *args, idle_timeout=10):
        super().__init__()
        self.idle_timeout = idle_timeout
        self.is_streaming = False
        self.starts = 0
        self.stops = 0
        self.failures = 0
        self.remote = ('active', 'our-auth-rid')

    async def start(self, area):
        self.starts += 1
        if self.failures:
            self.failures -= 1
            raise OSError('network unavailable')
        self.is_streaming = True
        self.remote = ('active', 'our-auth-rid')

    async def stop(self):
        self.stops += 1
        self.is_streaming = False

    async def aclose(self):
        self.is_streaming = False

    async def remote_status(self):
        return self.remote


def test_driver_disables_idle_and_seeds_keepalive(monkeypatch):
    import asyncio

    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', LifecycleSession)
    async def run():
        driver = HueDriver(_config(), _channels())
        await driver.start()
        session = driver._session
        assert session.idle_timeout == 0
        assert len(session.calls) == 1
        assert all(c.red == c.green == c.blue == 0 for c in session.calls[0])
        assert driver.output_status == {'state': 'streaming', 'reason': None}
        await driver.aclose()
        assert not session.is_streaming
        assert driver._health_task is driver._remote_task is driver._recovery_task is None
    asyncio.run(run())


def test_library_keepalive_resends_seeded_frame_without_audio():
    """Exercise the installed sender's actual empty-queue branch without a socket."""
    import queue
    from unittest.mock import Mock

    from hue_entertainment.dtls import HueDtlsStreamer

    streamer = HueDtlsStreamer()
    streamer._connected = True
    streamer._last_message = b'last frame'
    queue_stub = Mock()
    queue_stub.get.side_effect = queue.Empty
    streamer._send_queue = queue_stub
    connection = Mock()
    connection.send.side_effect = lambda frame: setattr(streamer, '_connected', False)
    streamer._sender_loop(connection)
    connection.send.assert_called_once_with(b'last frame')
    queue_stub.get.assert_called_once_with(timeout=5.0)
    connection.close.assert_called_once()


def test_silent_activation_and_lms_saved_auto_delay_reach_output(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from lampastream.latency import AutoLatencyProbe, NoLatencyProbe
    from lampastream.models import PlayerLatency, Profile
    from lampastream.sync_engine import SyncEngine
    from lampastream.types import AudioFeatures

    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', LifecycleSession)
    async def run(start_audio, delay):
        clock = [0.0]
        features = AudioFeatures(bars=[.1] * 30, bass=.1, mid=.1, centroid=.1, full=.1,
                                 onset=False, onset_strength=0)
        analyser = Mock()
        analyser.latest.side_effect = lambda: features if clock[0] >= start_audio else None
        probe = (AutoLatencyProbe(PlayerLatency(player_mac='lms', strategy='auto',
                   measured_delay_ms=delay), Mock(), Mock(), clock=lambda: clock[0])
                 if delay else NoLatencyProbe())
        engine = SyncEngine(None, Profile(), analyser=analyser, probe=probe)
        driver = HueDriver(_config(), _channels())
        await driver.start()
        session = driver._session
        frame_times = []
        original = session.send
        def send(commands):
            if session.is_streaming:
                frame_times.append(clock[0])
                original(commands)
        session.send = send
        async def tick(dt):
            clock[0] += dt
            # Model the exact library idle condition with a deterministic clock.
            if session.idle_timeout and clock[0] > session.idle_timeout:
                await session.stop()
            if clock[0] > start_audio + delay / 1000 + 2:
                raise asyncio.CancelledError
        monkeypatch.setattr('lampastream.sync_engine.time',
                            SimpleNamespace(monotonic=lambda: clock[0]))
        monkeypatch.setattr('lampastream.sync_engine.asyncio', SimpleNamespace(sleep=tick))
        try:
            await engine.run(driver)
        except asyncio.CancelledError:
            pass
        assert frame_times
        assert min(frame_times) >= start_audio + delay / 1000 - .04
        assert session.stops == 0
        assert session.is_streaming
        assert session.starts == 1
        await driver.aclose()
    asyncio.run(run(15, 0))
    asyncio.run(run(12, 3094))


def test_output_recovery_backoff_status_and_logs(monkeypatch, caplog):
    import asyncio

    from lampastream.models import Profile
    from lampastream.player_manager import ActiveSession, PlayerManager

    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', LifecycleSession)
    async def run():
        driver = HueDriver(_config(), _channels())
        await driver.start()
        # Own the recovery directly so this test's clock does not touch asyncio timers.
        driver._health_task.cancel()
        driver._remote_task.cancel()
        await asyncio.gather(driver._health_task, driver._remote_task, return_exceptions=True)
        driver._health_task = driver._remote_task = None
        session = driver._session
        session.is_streaming = False
        session.failures = 4
        manager = PlayerManager.__new__(PlayerManager)
        manager._active = ActiveSession(Profile())
        manager._active.hue_driver = driver
        assert not manager.bridge_connected
        assert manager.output_status['state'] == 'reconnecting'
        waits, states = [], []
        async def sleep(delay):
            waits.append(delay)
            states.append(manager.output_status['state'])
        driver._sleep = sleep
        driver._request_recovery('Light connection dropped')
        await driver._recovery_task
        assert waits == [1, 2, 5, 10, 10]
        assert 'failed' in states
        assert manager.output_status == {'state': 'streaming', 'reason': None}
        assert manager.bridge_connected
        assert session.starts == 6
        assert 'Light output down: Light connection dropped' in caplog.text
        assert 'Light output recovered: streaming' in caplog.text
        await driver.aclose()
    caplog.set_level('INFO')
    asyncio.run(run())


def test_bridge_end_and_controller_takeover_request_recovery(monkeypatch):
    import asyncio
    from unittest.mock import Mock

    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', LifecycleSession)
    async def run():
        driver = HueDriver(_config(), _channels())
        await driver.start()
        request = Mock()
        monkeypatch.setattr(driver, '_request_recovery', request)
        driver._session.remote = ('inactive', '')
        await driver._check_remote()
        request.assert_called_with('Bridge ended the light stream')
        driver._session.remote = ('active', 'another-auth-rid')
        await driver._check_remote()
        request.assert_called_with('Another controller took over the lights')
        await driver.aclose()
    asyncio.run(run())


def test_health_clock_detects_drop_and_api_reports_recovery(tmp_path, monkeypatch, caplog):
    import asyncio

    import httpx

    from lampastream.app import app
    from lampastream.models import Profile
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    class Clock:
        now = 0
        waiters = None
        def __init__(self):
            self.waiters = []
        async def sleep(self, seconds):
            future = asyncio.get_running_loop().create_future()
            self.waiters.append((self.now + seconds, future))
            await future
        async def advance(self, seconds):
            self.now += seconds
            for deadline, future in self.waiters:
                if deadline <= self.now and not future.done():
                    future.set_result(None)
            for _ in range(20):
                await asyncio.sleep(0)

    monkeypatch.setattr('lampastream.hue_output.EntertainmentSession', LifecycleSession)
    caplog.set_level('INFO')
    async def run():
        clock = Clock()
        driver = HueDriver(_config(), _channels())
        driver._sleep = clock.sleep
        await driver.start()
        await clock.advance(0)
        manager = PlayerManager(Storage(tmp_path / 'config.json'))
        manager._active = ActiveSession(Profile())
        manager._active.hue_driver = driver
        monkeypatch.setattr(app.state, 'player_manager', manager)
        monkeypatch.setattr(app.state, 'storage', manager.storage)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url='http://test') as client:
            driver._session.is_streaming = False
            await clock.advance(2)
            response = await client.get('/api/status')
            assert response.json()['output_status']['state'] == 'reconnecting'
            assert not response.json()['bridge_connected']
            assert driver._session.starts == 1  # one-second retry wait has not passed
            await clock.advance(1)
            response = await client.get('/api/status')
            assert response.json()['output_status'] == {'state': 'streaming', 'reason': None}
            assert response.json()['bridge_connected']
            assert driver._session.starts == 2
        assert 'Light output down:' in caplog.text
        assert 'Light output recovered: streaming' in caplog.text
        await driver.aclose()
    asyncio.run(run())
