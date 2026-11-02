"""Content coordinates, two different FLAC seek landings and startup acceptance."""

import asyncio
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from lampastream.canonicalizer import DataResult
from lampastream.latency import AutoLatencyProbe, FollowPositionContext
from lampastream.models import PlayerLatency
from lampastream.pcm_source import YeneyCoreShmStereoSource

ROOT = Path(__file__).resolve().parents[1]


def test_two_seek_landings_save_the_same_room_delay_and_lock_correctly():
    saved = []

    def simulate(requested, content):
        now = [100.0]
        ctx = FollowPositionContext(True, True, True, 1, 1, 100.0)
        follower = SimpleNamespace(
            _lampastream_mac="own",
            target_mac="room",
            position_alignment=(1, requested),
            latency_context=lambda: ctx,
        )
        config = PlayerLatency(
            "room",
            strategy="auto",
            measured_delay_ms=saved[-1] if saved else 141,
            measurement_basis="lms-content-v1" if saved else None,
        )
        probe = AutoLatencyProbe(
            config,
            follower,
            lambda value, stamp: saved.append(value),
            clock=lambda: now[0],
            position_clock=lambda: (content + now[0] - 100, now[0], content),
        )
        probe.cache["room"] = 0

        def value(mac, command):
            return (requested + now[0] - 100 - 0.012 if mac == "own" else 6.4 + now[0] - 100), now[
                0
            ]

        probe._value = value

        async def session():
            for second in range(1, 9):
                now[0] = 100.0 + second
                await probe.tick()
            # Actual content at this native clock point, relative to the room's origin.
            expected = content - 6.4
            assert abs(probe.current_delay_ms() / 1000 - expected) < 0.001
            assert probe.state == "stable"
            assert probe.startup_step_used and probe.mapping_generation == 1
            assert saved[-1] == 12
            # A later consensus is never allowed another startup jump.
            before = probe.current_delay_ms()
            now[0] = 120.0
            for _ in range(12):
                probe.accept(0.2, now[0], 12)
            assert abs(probe.current_delay_ms() - before) < 1e-6
            now[0] += 0.05
            assert abs(probe.current_delay_ms() - before) <= 0.250001

        asyncio.run(session())
        print(
            f"seek={requested:.3f}s actual={content:.9f}s saved={saved[-1]}ms; "
            "first locked beat error <1ms, one startup step"
        )

    for requested, content in [(6.316, 278528 / 44100), (6.273, 274432 / 44100)]:
        simulate(requested, content)
    assert max(saved) - min(saved) <= 10


def test_no_late_startup_step_and_missing_content_is_not_in_sync():
    now = [100.0]
    ctx = FollowPositionContext(True, True, True, 1, 1, 100.0)
    room = SimpleNamespace(latency_context=lambda: ctx)
    probe = AutoLatencyProbe(
        PlayerLatency("room", strategy="auto"),
        room,
        lambda *a: None,
        clock=lambda: now[0],
        position_clock=lambda: None,
    )
    probe.eligible(ctx, now[0])
    assert not probe.accept(0.2, 101.0)
    assert probe.state == "not measurable"
    now[0] = 116.0
    for _ in range(4):
        probe.accept(0.2, now[0], 12)
    assert not probe.startup_step_used
    assert probe.current_delay_ms() == 0
    assert probe.state == "measuring"
    now[0] += 0.1
    assert probe.current_delay_ms() == pytest.approx(0.5)


def test_patched_real_flac_decoder_exports_absolute_seek_content(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe unavailable")
    build = tmp_path / "core"
    shutil.copytree(
        ROOT / "third_party/yeney-core",
        build,
        ignore=shutil.ignore_patterns(".git", "*.o", "*.d", "*.a"),
    )
    with (ROOT / "scripts/patches/yeney-core-0001-content-position.patch").open() as patch:
        subprocess.run(["patch", "-d", str(build), "-p1"], stdin=patch, check=True)
    result = subprocess.run(
        ["make", "-C", str(build), "-j2", "yeney-player"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    flac = tmp_path / "seek.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=60:sample_rate=44100:duration=1",
            "-ac",
            "2",
            str(flac),
        ],
        check=True,
    )
    packets = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_packets",
                "-show_entries",
                "packet=pos,pts",
                "-of",
                "json",
                str(flac),
            ]
        )
    )["packets"]
    spec = importlib.util.spec_from_file_location("lat03_fake_lms", build / "tests/fake_lms.py")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    oracle.ROOT = build
    for index in (2, 3):
        packet = packets[index]
        first = int(packet["pts"])
        mac = "02:7d:" + ":".join(f"{b:02x}" for b in (os.getpid() + index).to_bytes(4, "big"))
        source = YeneyCoreShmStereoSource()
        source.use_player_clock = True
        shm = Path("/dev/shm/squeezelite-" + mac)
        try:
            with oracle.Session(app=True, sink="shm", app_args=["-v"], mac=mac) as session:
                source.open(mac, require_v1=True)
                session.lms.send("audg", struct.pack("!IIBBII", 0, 0, 1, 0, 0, 0))
                session.lms.strm(
                    "s", session.source(flac.read_bytes()[int(packet["pos"]) :]), fmt="f"
                )
                deadline = time.monotonic() + 5
                points = []
                while time.monotonic() < deadline:
                    frame = source.read()
                    if isinstance(frame, DataResult) and source.position_clock:
                        position, stamp, origin = source.position_clock
                        assert origin == pytest.approx(first / 44100, abs=1 / 44100)
                        assert position == pytest.approx(
                            (first + frame.frame.source_sample_pos) / 44100
                        )
                        assert stamp == frame.frame.play_monotonic
                        points.append(position)
                        if len(points) >= 5:
                            break
                    time.sleep(0.002)
                assert len(points) >= 5
                print(f"Native FLAC seek packet {index}: sample={first}, origin={origin:.9f}s")
        finally:
            source.close()
            shm.unlink(missing_ok=True)
