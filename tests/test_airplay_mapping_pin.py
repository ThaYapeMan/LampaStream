"""Baseline pin through the actual WebSocket event producer and CSV logger."""

import asyncio
import base64
import csv
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import websockets
from replay_chain import Replay, parser

from lampastream.airplay_timing import TimingDiagnostics
from lampastream.audible_clock import AirPlayAudibleClock
from lampastream.player_manager import PlayerManager
from lampastream.track_position import AirPlayTrackPositionSource

ROOT = Path(__file__).resolve().parents[1]


def baseline_module(name, path):
    module = types.ModuleType("lampastream._lat03_pin_" + name)
    module.__package__ = "lampastream"
    sys.modules[module.__name__] = module
    source = subprocess.check_output(["git", "show", "82181c5:" + path], cwd=ROOT, text=True)
    exec(compile(source, "82181c5:" + path, "exec"), module.__dict__)
    return module


def item(code, value=""):
    data = value.encode()
    return (
        f"<item><type>73736e63</type><code>{code.encode().hex()}</code>"
        f"<length>{len(data)}</length><data>{base64.b64encode(data).decode()}"
        "</data></item>"
    ).encode()


def test_airplay_actual_socket_detection_track_time_matches_82181c5(tmp_path, monkeypatch):
    from lampastream import app

    regenerate = os.environ.get("LAT03_GENERATE_AIRPLAY_PIN") == "1"
    if regenerate:
        old_clock = baseline_module("clock", "src/lampastream/audible_clock.py").AirPlayAudibleClock
        old_track = baseline_module(
            "track", "src/lampastream/track_position.py"
        ).AirPlayTrackPositionSource
        old_logger = baseline_module("logger", "scripts/ab-logger.py")
    spec = importlib.util.spec_from_file_location("lat03_logger", ROOT / "scripts/ab-logger.py")
    logger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(logger)
    messages = {}
    rate = 48000
    pcm = np.zeros(rate * 32, dtype=np.float32)
    t = np.arange(4800) / rate
    kick = 0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-55 * t)
    for stamp in np.arange(0.5, 31.7, 60 / 128):
        start = round(stamp * rate)
        pcm[start : start + len(kick)] += kick

    async def frames(websocket, *_):
        while True:
            await websocket.send_json(dict(type="frame", audible_t=0.0))
            await asyncio.sleep(0.05)

    monkeypatch.setattr(app, "_preview_frames", frames)

    def execute(label, clock_type, source_type, row_logger):
        timing = TimingDiagnostics()
        timing.tap_generation = 1
        timing.tap_source = "early tap"
        timing.rtp_clock = (0, 1.5, timing.tap_generation)
        source = source_type(timing=timing)
        # Identical synthetic progress/RTP anchor: track zero is audible at 1.5 s.
        with monkeypatch.context() as patch:
            patch.setattr("lampastream.track_position.time.monotonic", lambda: 0.0)
            patch.setattr(sys.modules[source_type.__module__].time, "monotonic", lambda: 0.0)
            source.feed(item("pbeg") + item("prgr", f"0/{2**32 - 66150}/{44100 * 32}"))
            track = source.read()
        manager = SimpleNamespace(track_position=track, _preview_listeners=set())
        manager.track_time_at = lambda stamp: PlayerManager.track_time_at(manager, stamp)
        manager.subscribe_preview = lambda callback: (
            manager._preview_listeners.add(callback)
            or (lambda: manager._preview_listeners.discard(callback))
        )
        args = parser().parse_args(
            [
                "--input",
                str(ROOT / "tests/fixtures/replay/clicks-128.wav"),
                "--config",
                str(ROOT / "tests/fixtures/tracker-baseline-config.json"),
                "--route",
                "timestamped",
                "--out",
                str(tmp_path / label),
            ]
        )
        replay = Replay(args)
        replay.analyse(np.column_stack([pcm, pcm]), rate)
        attach = replay.observe_mixer

        def observe(engine):
            attach(engine)
            engine.audible_clock = clock_type(timing=timing, lookahead=1.5)
            engine.preview_publish = lambda msg: PlayerManager._publish_preview(manager, msg)

        replay.observe_mixer = observe

        async def run():
            class Socket:
                app = SimpleNamespace(state=SimpleNamespace(player_manager=manager))

                def __init__(self, ws):
                    self.ws = ws

                async def accept(self):
                    pass

                async def receive_json(self):
                    return json.loads(await self.ws.recv())

                async def send_json(self, payload):
                    messages.setdefault(label, []).append(payload)
                    await self.ws.send(json.dumps(payload))

            async def handler(ws):
                try:
                    await app.ws_preview(Socket(ws))
                except websockets.ConnectionClosed:
                    pass

            async with websockets.serve(handler, "127.0.0.1", 0) as server:
                ready = tmp_path / (label + ".ready")
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                task = asyncio.create_task(row_logger.log(label, 120.0, tmp_path, url, ready))
                while not ready.exists() or not manager._preview_listeners:
                    await asyncio.sleep(0.001)
                try:
                    await replay.run()
                    expected = sum(
                        event.kind == "beat" and not event.predicted
                        for record in replay.records
                        for event in record.features.onset_events
                    )
                    assert expected >= 60
                    async with asyncio.timeout(15):
                        while True:
                            if task.done():
                                await task
                            with (tmp_path / f"{label}-beats.csv").open() as stream:
                                count = sum(
                                    row["source"] != "tempo_clock" for row in csv.DictReader(stream)
                                )
                            if count == expected:
                                break
                            await asyncio.sleep(0.001)
                finally:
                    task.cancel()
                    result = await asyncio.gather(task, return_exceptions=True)
                    assert isinstance(result[0], asyncio.CancelledError)

        try:
            asyncio.run(run())
        finally:
            replay.pipeline.stop()

    pin = ROOT / "tests/fixtures/ab-references/airplay-82181c5.csv"
    if regenerate:
        execute("baseline", old_clock, old_track, old_logger)
        golden = sorted(
            event["detected_audible_t"]
            for message in messages["baseline"]
            if message["type"] == "event"
            for event in message["events"]
            if event["kind"] == "beat" and not event["predicted"]
        )
        assert len(golden) >= 60
        with pin.open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(["detected_audible_t"])
            writer.writerows([[v] for v in golden])
    execute("current", AirPlayAudibleClock, AirPlayTrackPositionSource, logger)
    with pin.open() as stream:
        baseline = [float(row["detected_audible_t"]) for row in csv.DictReader(stream)]
    values = {"baseline": baseline}
    for label in ("current",):
        events = [
            event
            for message in messages[label]
            if message["type"] == "event"
            for event in message["events"]
            if event["kind"] == "beat" and not event["predicted"]
        ]
        wire_values = sorted(e["detected_audible_t"] for e in events)
        with (tmp_path / f"{label}-beats.csv").open() as stream:
            rows = [row for row in csv.DictReader(stream) if row["source"] != "tempo_clock"]
        assert all(row["audible_t"] == row["detected_audible_t"] for row in rows)
        values[label] = sorted(float(row["detected_audible_t"]) for row in rows)
        assert values[label] == wire_values
    assert len(values["baseline"]) >= 60
    assert values["current"] == pytest.approx(values["baseline"], abs=0.002)
    delta = max(abs(a - b) for a, b in zip(values["baseline"], values["current"], strict=True))
    print(
        f"Actual socket pin: {len(values['current'])} 128 BPM detections; "
        f"max baseline delta={delta * 1000:.6f}ms"
    )


def test_rtp_track_anchor_is_independent_of_metadata_receipt_delay(monkeypatch):
    times = [100.0]
    monkeypatch.setattr("lampastream.track_position.time.monotonic", lambda: times[0])
    timing = TimingDiagnostics()
    timing.tap_source = "early tap"
    timing.rtp_clock = (441000, 110.0, timing.tap_generation)
    source = AirPlayTrackPositionSource(timing=timing)
    for arrival in (100.0, 100.060, 99.940):
        times[0] = arrival
        source.feed(item("pbeg") + item("prgr", "0/0/1764000"))
        manager = SimpleNamespace(track_position=source.read())
        assert PlayerManager.track_time_at(manager, 110.5) == pytest.approx(10.5, abs=0.002)
    timing.tap_generation += 1
    assert timing.track_origin(0) is None


def test_native_playback_clock_shift_cannot_move_track_time(monkeypatch):
    monkeypatch.setattr("lampastream.track_position.time.monotonic", lambda: 100.0)
    timing = TimingDiagnostics()
    timing.tap_source = "early tap"
    source = AirPlayTrackPositionSource(timing=timing)
    source.feed(item("pbeg") + item("prgr", "0/0/1764000"))
    for shift in (0.0, 0.060, -0.020):
        timing.rtp_clock = (441000, 110.0 + shift, timing.tap_generation)
        event = 110.5 + shift
        old_mixed_clock = event - 100.0
        actual = PlayerManager.track_time_at(SimpleNamespace(track_position=source.read()), event)
        assert actual == pytest.approx(10.5, abs=0.002)
        print(
            f"native shift={shift * 1000:+.1f}ms: old={old_mixed_clock:.6f}s "
            f"RTP mapping={actual:.6f}s"
        )
