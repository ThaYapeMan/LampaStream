"""Continuous receiver PCM/metadata must survive switching either coupling direction."""

import asyncio
import os
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from test_player_manager import _make_airplay_storage
from test_track_position import item

import lampastream.player_manager as pm
from lampastream.airplay_early import EarlyAirPlaySource
from lampastream.canonicalizer import DataResult, DecodedSourceFrame
from lampastream.models import VirtualPlayer, VirtualPlayerType
from lampastream.pcm_source import AirPlayPipeStereoSource
from lampastream.track_position import AirPlayTrackPositionSource
from lampastream.types import OutputCapabilities


@pytest.mark.parametrize("initial", ["AirPlay", "LMS"])
def test_midtrack_receiver_survives_airplay_lms_airplay(tmp_path, monkeypatch, initial):
    storage, airplay = _make_airplay_storage(tmp_path)
    analyser = storage.get_analyser(airplay.analyser_id)
    analyser.spectrum_backend = "v2"
    storage.save_analyser(analyser)
    lms_player = VirtualPlayer(
        id="lms", player_mac="02:ff:01:02:03:04", type=VirtualPlayerType.LMS, head_start_ms=0
    )
    storage.save_virtual_player(lms_player)
    lms = replace(airplay, id="lms-coupling", name="LMS Room", player_id="lms")
    storage.save_coupling(lms)
    from lampastream.models import PlayerLatency
    storage.save_player_latency(PlayerLatency(
        "02:00:00:00:00:02", strategy="auto", measured_delay_ms=278380))
    manager = pm.PlayerManager(storage)
    fifo, metadata = tmp_path / "audio", tmp_path / "metadata"
    os.mkfifo(fifo)
    os.mkfifo(metadata)
    monkeypatch.setattr(
        pm, "AirPlayPipeStereoSource", lambda **kw: AirPlayPipeStereoSource(fifo, **kw)
    )
    monkeypatch.setattr(
        pm,
        "AirPlayTrackPositionSource",
        lambda **kw: AirPlayTrackPositionSource(str(metadata), **kw),
    )
    monkeypatch.setattr(
        pm,
        "EarlyAirPlaySource",
        lambda **kw: EarlyAirPlaySource(path=str(tmp_path / "absent-early-tap"), **kw),
    )
    monkeypatch.setattr(
        pm,
        "list_entertainment_areas",
        AsyncMock(return_value=[SimpleNamespace(id="ae-ap", name="Room")]),
    )
    monkeypatch.setattr(pm, "get_channel_infos", AsyncMock(return_value=[]))
    monkeypatch.setattr(manager, "_configure_shairport_name", lambda _: False)
    monkeypatch.setattr(manager, "_wait_for_shm", lambda _: None)
    monkeypatch.setattr(manager, "_start_lms_player", lambda *args: None)
    monkeypatch.setattr(manager, "_start_music", lambda *_: None)

    async def idle(*_):
        await asyncio.Future()

    monkeypatch.setattr(manager, "_poll_sync_master", idle)
    monkeypatch.setattr(manager, "_delayed_unsync_and_follow", idle)

    class PlayingLms:
        def open(self, *_):
            self.opened, self.position = True, 480000

        def read(self):
            time.sleep(0.005)
            start = self.position
            self.position += 480
            samples = np.repeat(
                (0.4 * np.sin(np.arange(start, start + 480) * 2 * np.pi * 100 / 48000))[:, None],
                2,
                axis=1,
            ).astype(np.float32)
            return DataResult(
                DecodedSourceFrame(
                    samples,
                    48000,
                    2,
                    "lms-live",
                    start,
                    False,
                    time.time_ns(),
                    time.monotonic(),
                    time.monotonic(),
                )
            )

        def close(self):
            self.opened = False

        @property
        def running(self):
            return self.opened

    monkeypatch.setattr(pm, "YeneyCoreShmStereoSource", PlayingLms)
    drivers = []

    class Driver:
        capabilities = OutputCapabilities()
        channels = []
        last_colours = []

        def __init__(self, *_):
            self.sends = 0
            self.stamps = []
            drivers.append(self)

        async def start(self):
            pass

        async def stop(self):
            pass

        async def aclose(self):
            pass

        def send(self, scene, stamp):
            self.sends += 1
            self.stamps.append(stamp)

    monkeypatch.setattr(pm, "HueDriver", Driver)
    stopped, broken = threading.Event(), threading.Event()
    writer_errors = []

    def sender():
        audio_fd = meta_fd = None
        try:
            audio_fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            meta_fd = os.open(metadata, os.O_WRONLY | os.O_NONBLOCK)
            os.write(
                meta_fd,
                item("pbeg")
                + item("prgr", "0/441000/16802100")
                + item("minm", "Already playing", "core"),
            )
            phase = 0
            while not stopped.is_set():
                samples = (
                    0.4 * np.sin(np.arange(phase, phase + 441) * 2 * np.pi * 100 / 44100) * 32767
                ).astype("<i2")
                phase += 441
                try:
                    os.write(audio_fd, np.repeat(samples[:, None], 2, axis=1).tobytes())
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    # Receiver output cannot continue until the sender/receiver restarts.
                    broken.set()
                    break
                stopped.wait(0.005)
        except OSError as error:
            writer_errors.append(str(error))
        finally:
            for fd in (audio_fd, meta_fd):
                if fd is not None:
                    os.close(fd)

    async def until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    async def exercise():
        from lampastream.audible_clock import AirPlayAudibleClock, LmsAudibleClock
        from lampastream.latency import AutoLatencyProbe
        from lampastream.lms_follower import LmsFollower

        clocks, probes, previews = [], [], []

        async def check_session():
            session = manager._active
            if session.player_type != VirtualPlayerType.AIRPLAY:
                # Install the real manual-follow probe with the poisoned field
                # estimate; position sampling itself is covered by the CLI replay.
                session.follower = LmsFollower(
                    "127.0.0.1", "02:00:00:00:00:02", session.profile.player_mac)
                await manager._apply_probe_for_master(session, session.follower.target_mac)
                assert isinstance(session.probe, AutoLatencyProbe)
                assert session.probe.current_delay_ms() < 5000
                assert session.probe.context is None
                assert not session.latency_preferences
                for i in range(7):
                    assert not session.probe.accept(278.345, 5 + i * 3)
                for i in range(4):
                    assert session.probe.accept(.350, 26 + i * 3)
                assert session.probe.current_delay_ms() == 350
                assert isinstance(session.sync_engine.audible_clock, LmsAudibleClock)
                assert session.sync_engine.audible_clock.timing is None
            else:
                assert isinstance(session.sync_engine.audible_clock, AirPlayAudibleClock)
                assert session.sync_engine.audible_clock.timing is manager.airplay_timing
            clock = session.sync_engine.audible_clock
            assert all(clock is not previous for previous in clocks)
            assert all(session.probe is not previous for previous in probes)
            from lampastream.types import AudioFeatures
            now = time.monotonic()
            features = AudioFeatures([], 0, 0, 0, 0,
                                     received_monotonic=now, play_monotonic=now)
            assert now <= clock.at(0, 0, features, now).audible < now + 5
            clocks.append(clock)
            probes.append(session.probe)
            await until(lambda: drivers[-1].sends > 2)
            assert abs(time.monotonic() - drivers[-1].stamps[-1]) < 3
            preview = session.sync_engine._audible_preview
            assert all(preview is not previous for previous in previews)
            previews.append(preview)

        thread = None
        try:
            await manager.activate_coupling(airplay if initial == "AirPlay" else lms)
            await asyncio.sleep(0.05)
            thread = threading.Thread(target=sender)
            thread.start()
            await until(
                lambda: manager._airplay_tracks.read() is not None and drivers[-1].sends > 2
            )
            await check_session()
            assert manager.airplay_timing.snapshot()["playback_since"] is not None
            if initial == "LMS":
                await manager.activate_coupling(airplay)
                await check_session()
                assert manager.track_position.title == "Already playing"
            assert not writer_errors
            receiver_anchor = manager.airplay_timing.snapshot()["playback_since"]
            assert receiver_anchor is not None
            await manager.activate_coupling(lms)
            await check_session()
            assert manager.airplay_timing.snapshot()["playback_since"] == receiver_anchor
            await asyncio.sleep(0.05)
            assert not broken.is_set(), "AirPlay FIFO lost its only reader during LMS switch"
            await manager.activate_coupling(airplay)
            await check_session()
            assert manager.track_position.title == "Already playing"
            assert manager.track_position.duration_s == 381.0
            assert manager._active.task is not None and not manager._active.task.done()
            assert manager.last_energy > 0
        finally:
            stopped.set()
            if thread:
                thread.join(timeout=2)
            await manager.close()

    asyncio.run(exercise())


def test_standby_reader_timeout_retains_descriptor_for_retry():
    from unittest.mock import Mock

    import pytest

    from lampastream.airplay_receiver import AirPlayReceiver

    entered, release = threading.Event(), threading.Event()
    source = Mock()

    def read():
        entered.set()
        release.wait(5)

    source.read.side_effect = read
    receiver = AirPlayReceiver(source)
    receiver.start()
    try:
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match="retiring"):
            receiver.acquire()
        source.close.assert_not_called()
        release.set()
        assert receiver.acquire() is source
        with pytest.raises(RuntimeError, match="Analysis still owns"):
            receiver.close()
        source.close.assert_not_called()
        receiver.release()
        receiver.close()
        source.close.assert_called_once()
    finally:
        release.set()
        receiver.leased = False
        receiver.close()


def test_cancelled_receiver_acquisition_returns_standby_lease(tmp_path, monkeypatch):
    manager = pm.PlayerManager(pm.Storage(tmp_path / "cancel-config.json"))
    entered, finish = threading.Event(), threading.Event()
    receiver = Mock(leased=False)

    def acquire():
        entered.set()
        finish.wait(2)
        receiver.leased = True
        return Mock()

    receiver.acquire.side_effect = acquire
    receiver.release.side_effect = lambda: setattr(receiver, "leased", False)
    manager._airplay_receiver = receiver
    manager._airplay_tracks = Mock()
    monkeypatch.setattr(manager, "start", lambda: None)
    session = pm.ActiveSession(pm.Profile())

    async def exercise():
        task = asyncio.create_task(
            manager._activate_airplay(session, session.profile, None, None, [])
        )
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not receiver.leased
        receiver.release.assert_called_once()
        assert session.shm_source is None

    asyncio.run(exercise())
