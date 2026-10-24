#!/usr/bin/env python3
"""Replay local PCM through production DSP, mixer, renderers and SyncEngine.run.

No source worker, player, bridge or service is started. Runtime adaptation and
observers are confined to this offline process; run_acceptance remains unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import random
import sys
import time
import wave
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import run_acceptance as acceptance  # noqa: E402

from lampastream import sync_engine as sync  # noqa: E402
from lampastream.canonicalizer import (  # noqa: E402
    AudioCanonicalizer,
    CanonicalData,
    DataResult,
    DecodedSourceFrame,
    EndOfStream,
)
from lampastream.models import (  # noqa: E402
    Analyser,
    Controller,
    Coupling,
    Effect,
    EnergyProfile,
    VirtualPlayer,
    Zone,
)
from lampastream.player_manager import (  # noqa: E402
    _build_engine_profile,
    _build_mellow_profile,
    _make_canonical_pipeline,
)
from lampastream.schema import empty_config, validate_current  # noqa: E402
from lampastream.storage import Storage  # noqa: E402
from lampastream.trace_output import TraceOutput, load_room  # noqa: E402

BANDS = ("all", "bass", "mid", "treble")
RATE = 48000
HOP = 480


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stable(value):
    """Canonical finite six-decimal traces, never locale/platform float repr."""
    if isinstance(value, (float, np.floating)):
        return round(float(value), 6) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): stable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [stable(v) for v in value]
    return value


def write_json(path, value):
    path.write_text(json.dumps(stable(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def write_csv(path, rows, columns=None):
    columns = columns or (list(rows[0]) if rows else [])
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            row = stable(row)
            writer.writerow({key: json.dumps(value, separators=(",", ":"), sort_keys=True)
                             if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


class SnapshotStorage(Storage):
    """Use production profile composition without filesystem or runtime activation."""

    def __init__(self, data):
        self.data = data

    def _read(self):
        return self.data

    def read_configuration(self):
        return self.data


def profiles(raw, coupling_id=None):
    data = json.loads(raw)
    data = data.get("configuration", data)
    if "analyser" in data:
        compact = data
        data = empty_config()
        defaults = {
            "controllers": Controller(id="controller"),
            "virtual_players": VirtualPlayer(id="player"),
            "zones": Zone(id="zone", controller_id="controller"),
            "analysers": Analyser.from_dict({"id": "analyser", **compact.get("analyser", {})}),
        }
        # Explicit IDs in compact fields take precedence without duplicate kwargs.
        for key, entity in defaults.items():
            data[key] = [entity.to_dict()]
        high = Effect.from_dict({"id": "high", **compact.get("high_effect", {})})
        low = Effect.from_dict({"id": "low", **compact.get("low_effect", {})})
        data["effects"] = [high.to_dict(), low.to_dict()]
        energy = EnergyProfile.from_dict({"id": "energy", "high_energy_effect_id": high.id,
                                          "low_energy_effect_id": low.id,
                                          **compact.get("energy_profile", {})})
        data["energy_profiles"] = [energy.to_dict()]
        data["couplings"] = [Coupling.from_dict({"id": "coupling", "player_id": "player",
            "zone_id": "zone", "analyser_id": data["analysers"][0]["id"],
            "energy_profile_id": energy.id, **compact.get("coupling", {})}).to_dict()]
    validate_current(data, references=True)
    storage = SnapshotStorage(data)
    couplings = [c for c in storage.list_couplings()
                 if c.id == coupling_id] if coupling_id else storage.list_couplings()
    if not couplings or len(couplings) != 1:
        raise ValueError("Select exactly one coupling with --coupling-id (or provide one coupling)")
    coupling = couplings[0]
    if coupling.manual_energy_profile_id:
        coupling = replace(coupling, energy_profile_id=coupling.manual_energy_profile_id)
    high = _build_engine_profile(coupling, storage)
    low = _build_mellow_profile(coupling, storage)
    if high is None:
        raise ValueError("Coupling must reference a player, zone, analyser, energy and high effect")
    return high, low or high


def decode(path, start=0., duration=None):
    """Read integer PCM WAV natively; other local formats use acceptance's ffmpeg."""
    if not path.is_file():
        raise ValueError("--input must be a local file")
    if path.suffix.lower() != ".wav":
        ffmpeg = acceptance.find_ffmpeg()
        if not ffmpeg:
            raise ValueError("ffmpeg is required for non-WAV input")
        raw = acceptance.decode_audio(ffmpeg, path, start, duration)
        return (np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float32) / 32768,
                44100, {"encoding": "ffmpeg-s16le", "bits": 16, "channels": 2,
                        "sample_rate": 44100, "decoder": acceptance.ffmpeg_version(ffmpeg)})
    with wave.open(str(path), "rb") as stream:
        rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
        if channels not in (1, 2) or width not in (1, 2, 3, 4):
            raise ValueError("WAV must be integer PCM, 8/16/24/32 bit, mono or stereo")
        offset = min(stream.getnframes(), round(start * rate))
        stream.setpos(offset)
        count = stream.getnframes() - offset
        raw = stream.readframes(count if duration is None else min(count, round(duration * rate)))
    if width == 3:
        octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        integers = octets[:, 0] | octets[:, 1] << 8 | octets[:, 2] << 16
        integers = (integers ^ 0x800000) - 0x800000
    elif width == 1:
        integers = np.frombuffer(raw, dtype=np.uint8).astype(np.int32) - 128
    else:
        integers = np.frombuffer(raw, dtype=f"<i{width}")
    pcm = (integers.astype(np.float64) / 2 ** (width * 8 - 1)).astype(np.float32)
    return pcm.reshape(-1, channels), rate, {
        "encoding": "wav-pcm", "bits": width * 8, "channels": channels, "sample_rate": rate}


class TaggedScene:
    def __init__(self, scene, identity, route, generation):
        self.scene, self.scene_id, self.route, self.generation = scene, identity, route, generation

    def color_at(self, position, t):
        return self.scene.color_at(position, t)


class FinishedReplay(Exception):
    """End the injected sleep without a running task or worker to cancel."""


class Replay:
    def __init__(self, args):
        self.args = args
        self.high, self.low = profiles(args.config.read_bytes(), args.coupling_id)
        self.output = TraceOutput(load_room(args.room), args.route)
        self.pipeline = _make_canonical_pipeline(acceptance._OfflineSource(), self.high)
        self.features, self.records, self.availability = [], [], []
        self.energy, self.renders = [], []
        self.reads = Counter()
        self.render_records = {}
        self.tick_reads = []
        self.tick_renders = []
        self.now = 0.
        self.tick = 0
        self.cursor = 0
        self.current = None
        self.trace_candidates = {}

    def analyse(self, pcm, rate):
        canonicalizer = AudioCanonicalizer()
        # Fixed 10ms source reads; resampler output is split into canonical hops
        # so availability has an explicit sample boundary, independent of render rate.
        canonical_frames = []
        for pos in range(0, len(pcm), max(1, rate // 100)):
            samples = pcm[pos:pos + max(1, rate // 100)]
            result = DataResult(DecodedSourceFrame(
                samples, rate, pcm.shape[1], "replay", pos,
                bool(np.any(np.abs(samples) >= 1)), round(pos / rate * 1e9)))
            canonical_frames.extend(c.frame for c in canonicalizer.push(result)
                                    if isinstance(c, CanonicalData))
        canonical_frames.extend(c.frame for c in canonicalizer.push(EndOfStream())
                                if isinstance(c, CanonicalData))
        # Epoch UUIDs are labels, not DSP inputs. Normalize the single file epoch.
        for frame in canonical_frames:
            for offset in range(0, len(frame.samples), HOP):
                start = frame.sample_pos + offset
                part = replace(frame, samples=frame.samples[offset:offset + HOP],
                               sample_pos=start, epoch_id="replay-0001",
                               received_monotonic=start / RATE,
                               play_monotonic=start / RATE + self.args.lead_s,
                               timing_generation=1)
                self.capture(self.pipeline.feed(part), start + len(part.samples))
        self.sample_count = sum(len(f.samples) for f in canonical_frames)
        self.capture(self.pipeline.end_of_stream(), self.sample_count)
        self.pipeline._arrival_spans.clear()
        self.pipeline._play_spans.clear()
        self.pipeline._pub_queue.clear()
        self.pipeline._pub_seq = 0
        self.pipeline._pub_dropped = 0
        self.pipeline._latest_pub = None
        self.pipeline._latest_loudness_pub = None
        self.pipeline._latest_hpss_pub = None

    def capture(self, records, available):
        for record in records:
            self.records.append(record)
            self.availability.append(available)
            f = record.features
            row = {key: "" for key in acceptance.CSV_COLUMNS}
            row.update(t_s=record.sample_pos / RATE, backend=self.high.spectrum_backend,
                effective_backend=record.effective_spectrum_backend,
                effective_engine=record.effective_spectrum_backend, sequence=record.sequence,
                epoch=record.epoch, sample_start=record.sample_pos, sample_end=record.sample_end,
                effective_processor_ids=";".join(record.effective_processor_ids))
            for key in ("bass", "mid", "full", "centroid", "onset", "onset_strength",
                        "onset_bass", "onset_mid", "onset_treble", "onset_bass_strength",
                        "onset_mid_strength", "onset_treble_strength", "relative_exertion"):
                value = getattr(f, key)
                is_flag = key.startswith("onset") and "strength" not in key
                row[key] = int(value) if is_flag else value
            for i, bar in enumerate(f.bars):
                row[f"bar_{i:02d}"] = bar
            smooth = self.pipeline.v2_bar_smooth
            row.update(peak_ema=self.pipeline.v2_peak_ema or 0,
                       bars_smooth_mean=sum(smooth) / len(smooth) if smooth else 0,
                       bars_smooth_max=max(smooth) if smooth else 0)
            if record.carried_spectrum_interval:
                row["carried_spectrum_start"], row["carried_spectrum_end"] = \
                    record.carried_spectrum_interval
            row.update(availability_sample=available, publication_time_s=None,
                       carried_historical=int(record.carried_spectrum_interval is not None),
                       level=f.level, loudness_momentary_lufs=f.loudness_momentary_lufs,
                       loudness_short_term_lufs=f.loudness_short_term_lufs,
                       sustained_energy=f.sustained_energy, hpss_active=int(f.hpss_active),
                       percussive_energy=f.percussive_energy, harmonic_energy=f.harmonic_energy)
            self.features.append(row)

    def release(self):
        count = 0
        while self.cursor < len(self.records):
            index = self.cursor
            if self.availability[index] / RATE > self.now + 1e-10:
                break
            if self.args.publications_per_tick and count >= self.args.publications_per_tick:
                break
            old = self.records[index]
            self.pipeline._publish(epoch_id=old.epoch, sample_start=old.sample_pos,
                sample_end=old.sample_end, features=old.features,
                effective_spectrum_backend=old.effective_spectrum_backend,
                effective_processor_ids=old.effective_processor_ids,
                carried_spectrum_interval=old.carried_spectrum_interval)
            self.features[index]["publication_time_s"] = self.now
            count += 1
            self.cursor += 1

    def observe_reads(self):
        latest, drain = self.pipeline.latest, self.pipeline.drain_publications

        def read_latest():
            result = latest()
            self.current = self.pipeline._latest_pub
            return result

        def read_queue():
            result = drain()
            self.queued = {id(record.features): record for record in result}
            return result

        self.pipeline.latest = read_latest
        self.pipeline.drain_publications = read_queue
        self.queued = {}

    def observe_mixer(self, engine):
        mixer = engine._effect
        for index, layer in enumerate((mixer._active, mixer._mellow)):
            rng = getattr(layer._renderer, "_rng", None)
            if rng is not None:
                rng.seed(self.args.seed + index)
        render = mixer.render

        def traced(features, t):
            record = self.queued.get(id(features), self.current)
            sequence = record.sequence
            self.reads[sequence] += 1
            self.tick_reads.append(sequence)
            scene = render(features, t)
            identity = len(self.render_records) + 1
            self.render_records[identity] = sequence
            self.tick_renders.append(identity)
            for channel in self.output.channels:
                colour = scene.color_at(channel.position, t)
                self.renders.append({"render_id": identity, "virtual_time_s": self.now,
                    "render_argument_s": t, "route": self.args.route,
                    "sequence": sequence, "play_time_s": features.play_monotonic
                    if self.args.route == "timestamped" else None,
                    "high_effect": self.high.effect_type, "low_effect": self.low.effect_type,
                    "onset_consumed": int(features.onset), "channel_id": channel.channel_id,
                    "r": colour.r, "g": colour.g, "b": colour.b})
            return TaggedScene(scene, identity, self.args.route, features.timing_generation or 0)

        mixer.render = traced

    def finish_tick(self, engine):
        mixer = engine._effect
        selected = mixer.last_energy_input
        state = mixer._energy_input
        self.energy.append({"tick": self.tick, "virtual_time_s": self.now,
            "route": self.args.route, "energy_source": state.mode, "energy_value": selected,
            "mix_target": sync._smoothstep(selected, mixer._low, mixer._high),
            "mix": mixer.mix, "adaptive_floor": state.adaptive_floor,
            "adaptive_ceiling": state.adaptive_ceiling, "peak_envelope": state._peak_envelope,
            "consumed_sequences": list(self.tick_reads), "render_ids": list(self.tick_renders)})
        self.tick_reads.clear()
        self.tick_renders.clear()

    async def run(self):
        self.observe_reads()
        schedule = self.args.delay_schedule

        def delay():
            value = self.args.delay_ms
            for stamp, setting in schedule:
                if self.now + 1e-10 >= stamp:
                    value = setting
            return value

        timing = SimpleNamespace(tap_generation=1, tap_source="early tap",
                                 processing=lambda *a: None)
        engine = sync.SyncEngine(None, self.high, analyser=self.pipeline,
            mellow_profile=self.low, probe=SimpleNamespace(current_delay_ms=delay),
            timing=timing if self.args.route == "timestamped" else None)
        self.observe_mixer(engine)
        # Changing the rate is isolated to this offline process/context. The
        # production default and delay-depth formula remain the same algorithm.
        interval = 1 / self.args.render_hz
        tail = max(self.args.lead_s if self.args.route == "timestamped" else 0,
                   self.args.delay_ms / 1000, *(v / 1000 for _, v in schedule)) + 2 * interval
        final_release = self.sample_count / RATE
        if self.args.publications_per_tick:
            final_release = max(final_release, len(self.records) * interval /
                                self.args.publications_per_tick + interval)
        end = final_release + tail

        async def step(_interval):
            self.finish_tick(engine)
            self.tick += 1
            self.now = self.tick / self.args.render_hz
            if self.now > end + 1e-10:
                raise FinishedReplay
            self.release()

        await self.output.start()
        try:
            with patch.object(sync, "SEND_INTERVAL_S", interval):
                await engine.run(self.output, clock=lambda: self.now, sleep=step)
        except FinishedReplay:
            pass
        finally:
            await self.output.stop()
            self.pipeline.stop()
        if self.cursor != len(self.records):
            raise RuntimeError("Replay ended with unpublished records")

    def counters(self):
        sent_scenes = {row["scene_id"] for row in self.output.rows}
        sent_sequences = {self.render_records[identity] for identity in sent_scenes}
        rendered_sequences = set(self.reads)
        events = {}
        for band in BANDS:
            key = "onset" if band == "all" else f"onset_{band}"
            received = {r.sequence for r in self.records if getattr(r.features, key)}
            events[band] = {"received": len(received),
                "accepted": len(received & rendered_sequences),
                "merged": len((received & rendered_sequences) - sent_sequences)
                    if self.args.route == "timestamped" else 0,
                "rendered": sum(self.reads[s] for s in received),
                "expired": len((received & rendered_sequences) - sent_sequences)
                    if self.args.route == "normal" else 0,
                "lost": len(received - sent_sequences)}
        one = {"published": len(self.records),
            "consumed": sum(self.reads[s] == 1 for s in range(1, len(self.records) + 1)),
            "repeated": sum(self.reads[s] > 1 for s in range(1, len(self.records) + 1)),
            "skipped": sum(self.reads[s] == 0 for s in range(1, len(self.records) + 1)),
            "render_reads": sum(self.reads.values()),
            "repeat_reads": sum(max(0, n - 1) for n in self.reads.values())}
        sends = [row for row in self.output.rows if row["channel_id"] ==
                 self.output.channels[0].channel_id]
        bins = Counter(math.floor(row["virtual_time_s"]) for row in sends)
        counts = [bins[i] for i in range(max(1, math.ceil(self.now)))]
        return {"events": events, "publications": {self.args.route: one},
            "sends": len(sends), "sends_per_second": {
                "p50": float(np.percentile(counts, 50)), "p95": float(np.percentile(counts, 95)),
                "max": max(counts)}, "publication_queue_drops": self.pipeline.pub_dropped_count}

    def save(self, pcm_format):
        out = self.args.out
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / "features.csv", self.features,
                  list(dict.fromkeys(acceptance.CSV_COLUMNS + list(self.features[0])
                       if self.features else acceptance.CSV_COLUMNS)))
        write_csv(out / "energy.csv", self.energy)
        write_csv(out / "renders.csv", self.renders)
        write_csv(out / "sends.csv", self.output.rows)
        counters = self.counters()
        write_json(out / "counters.json", counters)
        write_json(out / "meta.json", {"trace_version": 1,
            "input_sha256": digest(self.args.input.read_bytes()), "format": pcm_format,
            "duration_s": self.sample_count / RATE, "git_commit": acceptance.git_commit(ROOT),
            "config_sha256": digest(self.args.config.read_bytes()), "seed": self.args.seed,
            "route": self.args.route, "render_hz": self.args.render_hz,
            "publications_per_tick": self.args.publications_per_tick,
            "delay_ms": self.args.delay_ms, "delay_schedule": self.args.delay_schedule,
            "lead_s": self.args.lead_s, "start_s": self.args.start,
            "room_sha256": digest(self.args.room.read_bytes()),
            "python_version": sys.version.split()[0], "numpy_version": np.__version__,
            "wall_time": {"basis": "virtual", "start_s": 0, "end_s": self.now}})
        return counters


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--coupling-id")
    result.add_argument("--route", choices=("normal", "timestamped"), default="normal")
    result.add_argument("--render-hz", type=int, choices=(20, 30, 50, 60), default=30)
    result.add_argument("--publications-per-tick", type=int, default=0,
                        help="0: all available; positive: delivery cap per tick")
    result.add_argument("--delay-ms", type=float, default=0)
    result.add_argument("--delay-schedule", type=json.loads, default=[],
                        help='JSON list of [virtual_seconds, delay_ms] pairs')
    result.add_argument("--lead-s", type=float, default=1.5)
    result.add_argument("--seed", type=int, default=0)
    result.add_argument("--start", type=float, default=0)
    result.add_argument("--duration", type=float)
    result.add_argument("--room", type=Path, default=ROOT / "tests/fixtures/rooms/two-channel.json")
    result.add_argument("--out", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if (args.publications_per_tick < 0 or any(not math.isfinite(v) or v < 0
            for v in (args.delay_ms, args.lead_s, args.start))
            or args.duration is not None and (
                not math.isfinite(args.duration) or args.duration <= 0)):
        raise ValueError("Counts/times must be finite and nonnegative; duration must be positive")
    if (not isinstance(args.delay_schedule, list) or any(
            not isinstance(pair, list) or len(pair) != 2 or
            any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in pair)
            for pair in args.delay_schedule)):
        raise ValueError("--delay-schedule must be a list of nonnegative [seconds,ms] pairs")
    args.delay_schedule.sort()
    started = time.perf_counter()
    # Seed only this offline execution; per-instance band RNGs are seeded too.
    random.seed(args.seed)
    np.random.seed(args.seed % 2**32)
    replay = Replay(args)
    pcm, rate, pcm_format = decode(args.input, args.start, args.duration)
    if not len(pcm):
        raise ValueError("Selected audio interval is empty")
    try:
        replay.analyse(pcm, rate)
        asyncio.run(replay.run())
        counters = replay.save(pcm_format)
    finally:
        replay.pipeline.stop()
    print(json.dumps(stable(counters), sort_keys=True))
    print(f"Execution wall time: {time.perf_counter() - started:.3f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
