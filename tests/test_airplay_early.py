"""Timestamped tap, clock-domain mapping, scheduling and receiver backpressure."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from lampastream.airplay_early import (
    DISCONTINUITY,
    FLUSH,
    OUT_OF_ORDER,
    PAUSE,
    RESUME,
    EarlyAirPlaySource,
    SceneSchedule,
    TapFramer,
    TapRecord,
)
from lampastream.airplay_timing import AirPlayAutoLatencyProbe, TimingDiagnostics
from lampastream.canonicalizer import (
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    StreamInvalidated,
    TemporarilyNoData,
)
from lampastream.models import PlayerLatency

ROOT = Path(__file__).resolve().parents[1]


def record(*, lead=0.5, now=10, rtp=100, generation=1, flags=0, frames=352, drops=0):
    # Raw clock is 42 seconds ahead of CLOCK_MONOTONIC, not interchangeable.
    return TapRecord(
        flags,
        rtp,
        frames,
        generation,
        round((now + 42 + lead) * 1e9),
        round((now + 42) * 1e9),
        round(now * 1e9),
        drops,
        b"\x10\0\x20\0" * frames,
    )


@pytest.mark.parametrize("lead", [0.5, 0.15, 0.098, 0.02])
def test_measured_lead_schedules_on_time_or_immediately(lead):
    now, processing = 10, 0.098
    tap = record(lead=lead)
    schedule = SceneSchedule()
    schedule.add("scene", tap.play_time, now + processing, 1)
    target = max(tap.play_time, now + processing)
    assert schedule.due(target - 0.0001, 1) is None
    assert schedule.due(target, 1) == ("scene", None)
    assert (target - tap.play_time) * 1000 == pytest.approx(max(0, 98 - lead * 1000))
    diagnostics = TimingDiagnostics(clock=lambda: now + processing)
    diagnostics.arrival(352, now)
    diagnostics.tap_source = "early tap"
    diagnostics.tap_arrival(lead, 4)
    diagnostics.processing(now, now + processing, now + processing)
    probe = AirPlayAutoLatencyProbe(
        PlayerLatency(player_mac="ap", strategy="auto"), diagnostics, 0, Mock()
    )
    status = probe.status()
    assert status["state"] == ("stable" if lead >= processing else "lagging")
    assert status["lag_ms"] == max(0, round(98 - lead * 1000))
    assert status["tap_drop_count"] == 4
    assert status["lead_p50_ms"] == pytest.approx(lead * 1000)


def test_framing_partial_reads_malformed_and_clock_mapping():
    framer = TapFramer()
    encoded = record().encode()
    assert framer.feed(encoded[:13]) == []
    decoded = framer.feed(encoded[13:])[0]
    assert decoded.play_time == pytest.approx(10.5)
    assert decoded.rtp == 100 and decoded.frames == 352
    with pytest.raises(ValueError, match="Malformed"):
        framer.feed(b"broken" + encoded)
    assert framer.feed(encoded)[0] == decoded


class Pipe:
    running = True

    def __init__(self):
        self.reads = self.discards = 0

    def open(self):
        pass

    def close(self):
        pass

    def discard_pending(self):
        self.discards += 1

    def read(self):
        self.reads += 1
        return TemporarilyNoData()


@pytest.fixture
def ingress(tmp_path):
    clock, pipe = [10.0], Pipe()
    path = tmp_path / "early.pcm"
    os.mkfifo(path)
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    source = EarlyAirPlaySource(timing=diagnostics, pipe=pipe, path=path, clock=lambda: clock[0])
    source.open()
    writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    try:
        yield source, writer, clock, pipe, diagnostics
    finally:
        os.close(writer)
        source.close()


def next_frame(source):
    for _ in range(8):
        result = source.read()
        if isinstance(result, DataResult):
            return result.frame
    raise AssertionError("No PCM frame received")


def test_stall_falls_back_once_and_recovers_without_receiver_restart(ingress, caplog):
    source, writer, clock, pipe, diagnostics = ingress
    caplog.set_level("INFO")
    os.write(writer, record().encode())
    frame = next_frame(source)
    assert frame.play_monotonic == 10.5
    assert pipe.reads == 0 and pipe.discards > 0
    assert diagnostics.snapshot()["lead_p5_ms"] == 500
    clock[0] += 0.999
    assert isinstance(source.read(), TemporarilyNoData)
    assert pipe.reads == 0
    clock[0] += 0.002
    assert isinstance(source.read(), StreamInvalidated)
    source.read()
    source.read()
    assert pipe.reads == 2
    assert caplog.text.count("tap missing or stale") == 1
    os.write(writer, record(now=clock[0], rtp=452).encode())
    assert next_frame(source).play_monotonic == pytest.approx(clock[0] + 0.5)
    assert diagnostics.tap_source == "early tap"
    assert caplog.text.count("timestamped PCM available") == 2


@pytest.mark.parametrize("flag", [FLUSH, PAUSE, DISCONTINUITY])
def test_control_markers_invalidate_scheduled_scenes(ingress, flag):
    source, writer, _, _, diagnostics = ingress
    os.write(writer, record().encode())
    frame = next_frame(source)
    schedule = SceneSchedule()
    schedule.add("never heard", frame.play_monotonic, 10, frame.timing_generation)
    os.write(writer, record(flags=flag, frames=0, generation=2).encode())
    assert isinstance(source.read(), StreamInvalidated)
    assert schedule.due(20, diagnostics.tap_generation) is None
    if flag == PAUSE:
        os.write(writer, record(rtp=452, generation=2).encode())
        assert isinstance(source.read(), TemporarilyNoData)
    os.write(writer, record(flags=RESUME, frames=0, generation=3).encode())
    assert isinstance(source.read(), StreamInvalidated)
    os.write(writer, record(rtp=452, generation=3).encode())
    assert next_frame(source).timing_generation == diagnostics.tap_generation


def test_duplicate_out_of_order_and_rtp_wrap_do_not_rewind(ingress):
    source, writer, _, _, _ = ingress
    os.write(writer, record(rtp=2**32 - 352).encode())
    next_frame(source)
    for flag in [0, OUT_OF_ORDER]:
        os.write(writer, record(rtp=2**32 - 352, flags=flag).encode())
        assert isinstance(source.read(), TemporarilyNoData)
    os.write(writer, record(rtp=0).encode())
    assert next_frame(source).play_monotonic == 10.5


def test_malformed_or_stale_backlog_falls_back_and_valid_records_recover(ingress):
    source, writer, clock, pipe, diagnostics = ingress
    os.write(writer, record().encode())
    next_frame(source)
    os.write(writer, b"bad" + record().encode())
    assert isinstance(source.read(), StreamInvalidated)
    source.read()
    assert pipe.reads == 1
    clock[0] = 12
    os.write(writer, record(now=10, rtp=452).encode())
    source.read()
    assert diagnostics.tap_source == "pipe fallback"
    os.write(writer, record(now=12, rtp=804).encode())
    next_frame(source)
    assert diagnostics.tap_source == "early tap"


def test_canonicalizer_preserves_play_time_across_resampling(ingress):
    source, writer, _, _, _ = ingress
    os.write(writer, record(frames=1000).encode())
    frame = next_frame(source)
    canonicalizer = AudioCanonicalizer(quality="LQ")
    results = canonicalizer.push(DataResult(frame))
    canonical = next(r.frame for r in results if isinstance(r, CanonicalData))
    assert canonical.play_monotonic == pytest.approx(frame.play_monotonic)
    assert canonical.timing_generation == frame.timing_generation
    assert canonical.received_monotonic == 10


def test_slow_scene_consumer_is_bounded_and_sends_latest_due():
    schedule = SceneSchedule(capacity=10)
    for i in range(100):
        schedule.add(i, 10 + i / 100, 10, 1)
    assert len(schedule.queue) == 10
    assert schedule.due(20, 1) == (99, None)
    assert not schedule.queue


@pytest.fixture(scope="module")
def c_writer(tmp_path_factory):
    """Compile the actual new C writer from the patch, with clock/config stubs."""
    path = tmp_path_factory.mktemp("tap-writer")
    patch = (ROOT / "scripts/patches/shairport-sync-0002-early-tap.patch").read_text()
    for name in ["early_tap.c", "early_tap.h"]:
        section = patch.split(f"diff --git a/{name} b/{name}\n")[1].split("\ndiff --git ")[0]
        (path / name).write_text(
            "\n".join(
                s[1:] for s in section.splitlines() if s.startswith("+") and not s.startswith("+++")
            )
            + "\n"
        )
    (path / "common.h").write_text("""#ifndef COMMON_H
#define COMMON_H
#include <stdint.h>
typedef struct {
  int connection_number, input_rate, input_bit_depth, input_bytes_per_frame;
} rtsp_conn_info;
extern struct cfg { char *early_tap_pipe; } config;
uint64_t get_absolute_time_in_ns(void);
void inform(const char *, ...);
#endif
""")
    (path / "rtp.h").write_text(
        '#include "common.h"\nint frame_to_local_time(uint32_t, uint64_t *, rtsp_conn_info *);\n'
    )
    (path / "test.c").write_text("""#include "early_tap.c"
#include <stdio.h>
#include <signal.h>
struct cfg config;
uint64_t get_absolute_time_in_ns(void) {
  struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW, &t);
  return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
}
void inform(const char *fmt, ...) { (void)fmt; }
int frame_to_local_time(uint32_t r, uint64_t *t, rtsp_conn_info *c) {
  (void)r; (void)c; *t=get_absolute_time_in_ns()+500000000; return 0;
}
int main(int argc, char **argv) {
  (void)argc; signal(SIGPIPE, SIG_IGN); config.early_tap_pipe=argv[1];
  rtsp_conn_info c={1,44100,16,4}; int16_t pcm[2000]={123,-123};
  for(int i=0;i<32;i++) early_tap(&c,pcm,1000,i*1000,0);
  printf("%llu\\n", (unsigned long long)atomic_load(&drops));
}
""")
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(path / "test.c"),
            "-o",
            str(path / "writer"),
        ],
        check=True,
    )
    return path / "writer"


def test_c_writer_no_reader_and_full_fifo_never_block_or_corrupt(c_writer, tmp_path):
    path = tmp_path / "pcm"
    os.mkfifo(path)
    result = subprocess.run(
        [str(c_writer), str(path)], capture_output=True, text=True, timeout=2, check=True
    )
    assert int(result.stdout) == 32
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        result = subprocess.run(
            [str(c_writer), str(path)], capture_output=True, text=True, timeout=2, check=True
        )
        drops = int(result.stdout)
        assert 0 < drops < 32
        records = TapFramer().feed(os.read(reader, 65536))
        assert len(records) == 32 - drops
        assert all(r.frames == 1000 and len(r.pcm) == 4000 for r in records)
        assert records[0].pcm[:4] == b"{\0\x85\xff"
    finally:
        os.close(reader)


def test_native_publications_keep_rtp_play_times(ingress):
    from pipeline_factory import make_pipeline

    source, writer, _, _, _ = ingress
    canonicalizer = AudioCanonicalizer(quality="LQ")
    from lampastream.models import Profile

    profile = Profile()
    settings = {
        key: getattr(profile, key)
        for key in (
            "onset_method",
            "onset_delta",
            "onset_alpha",
            "superflux_mu",
            "superflux_lag",
            "bass_hz",
            "mid_hz",
        )
    }
    pipeline = make_pipeline(source=None, **settings)
    try:
        for i in range(4):
            os.write(
                writer,
                record(rtp=100 + i * 1000, frames=1000, lead=0.5 + i * 1000 / 44100).encode(),
            )
            for result in canonicalizer.push(DataResult(next_frame(source))):
                if isinstance(result, CanonicalData):
                    pipeline._process_canonical_frame(result.frame)
        publications = pipeline.drain_publications()
        assert publications
        for publication in publications:
            assert publication.features.play_monotonic == pytest.approx(
                10.5 + publication.sample_pos / 48000
            )
            assert publication.features.timing_generation == source.timing.tap_generation
    finally:
        pipeline.stop()


@pytest.mark.parametrize("lead", [0.5, 0.15, 0.098, 0.02])
@pytest.mark.parametrize("flush", [False, True])
def test_production_output_loop_obeys_targets_and_flush(monkeypatch, lead, flush):
    import asyncio
    from types import SimpleNamespace

    from lampastream.models import Profile
    from lampastream.sync_engine import SEND_INTERVAL_S, CanonicalAnalysisPipeline, SyncEngine
    from lampastream.types import AudioFeatures

    clock = [10.098]
    diagnostics = TimingDiagnostics(clock=lambda: clock[0])
    diagnostics.arrival(352, 10)
    diagnostics.tap_source = "early tap"
    diagnostics.tap_generation = 1
    diagnostics.tap_arrival(lead, 0)
    diagnostics.processing(10, clock[0], clock[0])
    features = AudioFeatures(
        bars=[0.3] * 30,
        bass=0.3,
        mid=0.3,
        full=0.3,
        centroid=0.3,
        onset=False,
        onset_strength=0,
        received_monotonic=10,
        play_monotonic=10 + lead,
        timing_generation=1,
    )

    class TimedPipeline(CanonicalAnalysisPipeline):
        def __init__(self):
            self.records = [SimpleNamespace(features=features)]

        def drain_publications(self):
            result, self.records = self.records, []
            return result

    async def run():
        output = Mock()
        probe = AirPlayAutoLatencyProbe(
            PlayerLatency(player_mac="ap", strategy="auto"), diagnostics, 0, Mock()
        )
        engine = SyncEngine(
            None, Profile(), analyser=TimedPipeline(), probe=probe, timing=diagnostics
        )

        async def tick(dt):
            clock[0] += dt
            if flush and clock[0] >= 10.12:
                diagnostics.tap_generation = 2
            if clock[0] > max(10.098, 10 + lead) + dt * 2:
                raise asyncio.CancelledError

        monkeypatch.setattr(
            "lampastream.sync_engine.time", SimpleNamespace(monotonic=lambda: clock[0])
        )
        monkeypatch.setattr("lampastream.sync_engine.asyncio", SimpleNamespace(sleep=tick))
        try:
            await engine.run(output)
        except asyncio.CancelledError:
            pass
        if flush and lead > 0.12:
            output.send.assert_not_called()
        else:
            output.send.assert_called_once()
            sent = output.send.call_args.args[1]
            assert max(10.098, 10 + lead) <= sent < max(10.098, 10 + lead) + SEND_INTERVAL_S

    asyncio.run(run())


def test_old_generation_cannot_undo_a_flush(ingress):
    source, writer, _, _, _ = ingress
    os.write(writer, record().encode())
    next_frame(source)
    os.write(writer, record(flags=FLUSH, generation=2, frames=0).encode())
    assert isinstance(source.read(), StreamInvalidated)
    os.write(writer, record(rtp=452, generation=1).encode())
    assert isinstance(source.read(), TemporarilyNoData)
    os.write(writer, record(rtp=452, generation=2).encode())
    assert next_frame(source).play_monotonic == 10.5


def test_metadata_pause_cancels_even_when_tap_marker_is_lost(ingress):
    source, writer, _, _, diagnostics = ingress
    os.write(writer, record().encode())
    frame = next_frame(source)
    schedule = SceneSchedule()
    schedule.add("cancelled", frame.play_monotonic, 10, frame.timing_generation)
    diagnostics.metadata("paus", "")
    assert isinstance(source.read(), StreamInvalidated)
    assert schedule.due(20, diagnostics.tap_generation) is None
    os.write(writer, record(rtp=452).encode())
    assert isinstance(source.read(), TemporarilyNoData)
    diagnostics.metadata("pres", "")
    os.write(writer, record(rtp=452, generation=2, flags=RESUME).encode())
    assert next_frame(source).play_monotonic == 10.5


@pytest.mark.parametrize("strategy", ["fixed", "none"])
def test_details_keep_live_tap_measurements_for_manual_strategies(tmp_path, strategy):
    from lampastream.models import Profile, VirtualPlayerType
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    manager = PlayerManager(Storage(tmp_path / "config.json"))
    config = PlayerLatency(player_mac="ap", strategy=strategy)
    manager._active = ActiveSession(Profile(player_mac="ap"), player_type=VirtualPlayerType.AIRPLAY)
    manager._active.latency_mac = "ap"
    manager._active.probe = Mock()
    manager._active.probe.current_delay_ms.return_value = 0
    manager.airplay_timing.tap_source = "early tap"
    manager.airplay_timing.tap_arrival(0.15, 7)
    status = manager.latency_status(config)
    assert status["audio_source"] == "early tap"
    assert status["lead_p5_ms"] == status["lead_p50_ms"] == 150
    assert status["tap_drop_count"] == 7


def test_replaced_fifo_is_reopened_without_a_second_reader(ingress):
    source, writer, clock, pipe, diagnostics = ingress
    os.write(writer, record().encode())
    next_frame(source)
    os.unlink(source.path)
    os.mkfifo(source.path)
    clock[0] = 11.01
    source.read()  # closes the old inode before opening the replacement
    replacement = os.open(source.path, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(replacement, record(now=clock[0], generation=2).encode())
        assert next_frame(source).play_monotonic == pytest.approx(11.51)
        assert diagnostics.snapshot()["tap_source"] == "early tap"
    finally:
        os.close(replacement)
