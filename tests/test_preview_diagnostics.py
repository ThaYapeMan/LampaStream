"""Trigger metrics are generic status facts on every active player's route."""

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from lampastream.api import get_status
from lampastream.audible_preview import diagnostic_status


@pytest.mark.parametrize("kind", ["LMS", "AirPlay"])
def test_status_and_socket_report_measured_trigger_ratio(kind):
    app = importlib.import_module("lampastream.app")

    class Manager:
        active_player_type = kind
        last_bars = []
        last_loudness = (None, None)
        preview_spectrum = ([], None)
        preview_frame = dict(
            channel_colours=[],
            colour=dict(r=0, g=0, b=0),
            onset=False,
            pcm_onset=False,
            onset_bass=False,
            onset_mid=False,
            onset_treble=False,
            trigger_ratio=1.23,
            agc_gain=2.5,
        )

        def __getattr__(self, _):
            return None

    manager = Manager()
    messages = []

    class Socket:
        app = SimpleNamespace(
            state=SimpleNamespace(storage=SimpleNamespace(get_coupling=lambda _: None,
                                                    get_energy_profile=lambda _: None),
                                  player_manager=manager)
        )

        async def send_json(self, message):
            messages.append(message)
            if message["type"] == "status":
                raise WebSocketDisconnect()

        async def close(self):
            pass

    async def exercise():
        await app._preview_frames(Socket(), manager)
        status = await get_status(SimpleNamespace(app=Socket.app))
        assert status["trigger_ratio"] == 1.23 and status["agc_gain"] == 2.5

    asyncio.run(exercise())
    frame = next(m for m in messages if m["type"] == "frame")
    status = next(m for m in messages if m["type"] == "status")
    assert frame["trigger_ratio"] == status["trigger_ratio"] == 1.23


def test_unknown_or_invalid_metric_is_null():
    assert diagnostic_status({}) == dict(trigger_ratio=None, agc_gain=None)
    assert diagnostic_status(dict(trigger_ratio=float("nan")))["trigger_ratio"] is None


def test_socket_status_uses_its_application_storage(monkeypatch):
    from fastapi import FastAPI

    module = importlib.import_module("lampastream.app")
    # The module's app is a different application, with no storage configured.
    monkeypatch.setattr(module, "app", FastAPI())

    class Manager:
        active_coupling_id = "coupling"
        active_energy_profile_id = "energy"
        last_bars = []
        last_loudness = (None, None)
        preview_spectrum = ([], None)
        preview_frame = dict(channel_colours=[], colour=dict(r=0, g=0, b=0),
                             onset=False, pcm_onset=False, onset_bass=False,
                             onset_mid=False, onset_treble=False,
                             trigger_ratio=.9, agc_gain=32.)

        def __getattr__(self, _):
            return None

    calls, messages = [], []

    def coupling(identity):
        calls.append(("coupling", identity))
        return SimpleNamespace(beat_accent_mode="tracker")

    def energy(identity):
        calls.append(("energy", identity))
        return SimpleNamespace(agc_max_gain=32.)

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(storage=SimpleNamespace(
            get_coupling=coupling, get_energy_profile=energy)))

        async def send_json(self, message):
            messages.append(message)
            if message["type"] == "status":
                raise WebSocketDisconnect()

        async def close(self):
            pass

    asyncio.run(module._preview_frames(Socket(), Manager()))
    status = next(message for message in messages if message['type'] == 'status')
    assert status['beat_accent_mode'] == 'tracker'
    assert status['agc_max_gain'] == 32.
    assert calls == [('coupling', 'coupling'), ('energy', 'energy')]
