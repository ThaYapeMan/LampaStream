"""Synthetic 128 BPM kicks through canonical analysis/render and real socket producer."""

import asyncio
import importlib
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from replay_chain import Replay, decode, parser

from lampastream.lms_status import _parse_status
from lampastream.player_manager import PlayerManager
from lampastream.track_position import AirPlayTrackPositionSource, LmsTrackPositionSource


@pytest.mark.parametrize("route", ["normal", "timestamped"])
def test_128_bpm_pulse_events_on_socket(tmp_path, monkeypatch, route):
    app = importlib.import_module("lampastream.app")
    rate, period = 48000, 0.46875
    pcm = np.zeros(rate * 12)
    for stamp in np.arange(0.5, 11.7, period):
        start = round(stamp * rate)
        t = np.arange(4800) / rate
        pcm[start : start + len(t)] += 0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 55)
    path = tmp_path / "128-pulse.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes((pcm * 32767).astype("<i2").tobytes())
    args = parser().parse_args(
        [
            "--input",
            str(path),
            "--config",
            str(Path(__file__).parent / "fixtures/replay/default-config.json"),
            "--route",
            route,
            "--out",
            str(tmp_path / "trace"),
        ]
    )
    replay = Replay(args)
    messages = []
    subscribers = []

    class Socket:
        app = SimpleNamespace(
            state=SimpleNamespace(
                player_manager=SimpleNamespace(
                    subscribe_preview=lambda callback: (
                        subscribers.append(callback) or (lambda: None)
                    )
                )
            )
        )

        async def accept(self):
            pass

        async def receive_json(self):
            await asyncio.Future()

        async def send_json(self, payload):
            messages.append(payload)

    async def frames(*_):
        await asyncio.Future()

    monkeypatch.setattr(app, "_preview_frames", frames)
    observe = replay.observe_mixer

    def attach(engine):
        observe(engine)
        engine.preview_publish = lambda message: [callback(message) for callback in subscribers]

    replay.observe_mixer = attach

    async def exercise():
        task = asyncio.create_task(app.ws_preview(Socket()))
        await asyncio.sleep(0)
        try:
            audio, sample_rate, _ = decode(args.input)
            replay.analyse(audio, sample_rate)
            await replay.run()
            await asyncio.sleep(0.02)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            replay.pipeline.stop()

    asyncio.run(exercise())
    beats = [
        event
        for message in messages
        if message["type"] == "event"
        for event in message["events"]
        if event["kind"] == "beat" and not event["predicted"]
    ]
    stamps = sorted(event["detected_audible_monotonic"] for event in beats)
    assert len(stamps) >= 20
    assert np.diff(stamps) == pytest.approx(np.full(len(stamps) - 1, period), abs=0.01)
    assert all(0 <= event["strength"] <= 1 for event in beats)
    assert all(event["audible_monotonic"] >= event["detected_audible_monotonic"] for event in beats)
    print(
        f"{route}: {len(stamps)} beat events; detection spacing "
        f"{np.diff(stamps).min():.8f}..{np.diff(stamps).max():.8f} s"
    )


@pytest.mark.parametrize("player_kind", ["AirPlay", "LMS"])
def test_generic_player_anchor_maps_preview_track_time(player_kind, monkeypatch):
    # Feed each real player metadata adapter; both expose the same status contract.
    monkeypatch.setattr("lampastream.track_position.time.monotonic", lambda: 100.0)
    if player_kind == "AirPlay":
        import base64

        source = AirPlayTrackPositionSource()

        def item(code, text=""):
            data = text.encode()
            return (
                f"<item><type>73736e63</type><code>{code.encode().hex()}</code>"
                f"<length>{len(data)}</length><data>{base64.b64encode(data).decode()}"
                "</data></item>"
            ).encode()

        source.feed(item("pbeg") + item("prgr", "0/441000/16802100"))
    else:
        source = LmsTrackPositionSource("unused", lambda: "room")
        source.seed("room", _parse_status("mode:play time:10 duration:381"), 100.0)
    track = source.read()
    assert track.for_delivery()["position_s"] == 10.0
    assert track.for_delivery()["duration_s"] == 381.0
    manager = SimpleNamespace(track_position=track)
    assert PlayerManager.track_time_at(manager, 100.46875) == 10.46875
    manager.track_position = None
    assert PlayerManager.track_time_at(manager, 100.46875) is None
