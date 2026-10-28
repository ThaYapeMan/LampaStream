"""Offline evidence only: current bugs are pinned explicitly, not repaired here."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from hue_entertainment import LightColorCommand
from hue_entertainment.dtls import HueDtlsStreamer

from lampastream.trace_output import TraceOutput, load_room, wire_rgb
from lampastream.types import Colour, UniformScene

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/replay"
ROOM = ROOT / "tests/fixtures/rooms/two-channel.json"


def rows(out, name):
    with (out / name).open() as stream:
        return list(csv.DictReader(stream))


def run(out, *options, config=None, audio=None):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/replay_chain.py"),
        "--diagnostic-onsets",
        "--input", str(audio or FIXTURES / "clicks-120.wav"),
        "--config", str(config or FIXTURES / "default-config.json"),
        "--out", str(out), *options], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((out / "counters.json").read_text())


def hashes(out):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()
            if p.is_file()}


@pytest.fixture(scope="module")
def references(replay_cache):
    result = {}
    for route in ("normal", "timestamped"):
        for hz in (30, 60):
            replay = replay_cache.get("clicks-120", route, hz)
            out, counters = replay["out"], replay["counters"]
            result[route, hz] = out, counters
    return result


def test_click_truth_count_and_candidate_reported_fields_present(references):
    out, counters = references["normal", 30]
    truth = json.loads((FIXTURES / "clicks-120.json").read_text())["event_samples"]
    assert abs(counters["events"]["all"]["received"] - len(truth)) <= 1
    onsets = [r for r in rows(out, "features.csv") if r["onset"] == "1"]
    assert onsets
    for event in onsets:
        for key in ("candidate_sample_all", "reported_sample_all", "candidate_strength_all",
                    "reported_strength_all", "decision_sample_all", "availability_sample"):
            assert event[key] != ""  # REG-01, not BENCH-01, will assert the mismatch's values.
    assert len({r["event_id_all"] for r in onsets}) == len(onsets)


@pytest.mark.parametrize("route", ["normal", "timestamped"])
def test_every_publication_accounted_at_30_and_60_hz(references, route):
    for hz in (30, 60):
        out, counters = references[route, hz]
        features = rows(out, "features.csv")
        energy = rows(out, "energy.csv")
        published = len(features)
        ledger = counters["publications"][route]
        assert ledger["published"] == published
        assert sum(ledger[k] for k in ("consumed", "repeated", "skipped")) == published
        assert sum(sum(int(t[f"{key}_count"]) for key in
                       ("consumed", "repeated", "skipped")) for t in energy) == published
        classified = [seq for t in energy for key in ("consumed", "repeated", "skipped")
                      for seq in json.loads(t[f"{key}_publication_sequences"])]
        assert sorted(classified) == list(range(1, published + 1))
        reads = [seq for t in energy for seq in json.loads(t["consumed_sequences"])]
        assert len(reads) == ledger["render_reads"]
        assert len(reads) - len(set(reads)) == ledger["repeat_reads"]


@pytest.mark.parametrize("effect,playback", [
    ("spectrum_rgb", "static"), ("splotches", "static"), ("fireworks", "static"),
    ("band_colours", "shuffle"), ("band_colours", "random"), ("band_colours", "mix"),
])
def test_all_trace_files_byte_identical_across_processes(tmp_path, effect, playback):
    data = json.loads((FIXTURES / "default-config.json").read_text())
    data["configuration"]["effects"][0].update(effect_type=effect, band_playback=playback)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(data))
    for name in ("one", "two"):
        run(tmp_path / name, "--duration", "2", "--route", "timestamped", "--seed", "1729",
            config=config)
    assert hashes(tmp_path / "one") == hashes(tmp_path / "two")
    assert set(hashes(tmp_path / "one")) == {
        "features.csv", "events.csv", "energy.csv", "renders.csv", "sends.csv",
        "counters.json", "meta.json", "latency.csv"}


def test_pins_current_normal_delay_shrink_burst_not_a_fix(tmp_path):
    out = tmp_path / "burst"
    run(out, "--duration", "2", "--delay-ms", "500",
        "--delay-schedule", "[[1,0]]")
    sends = [r for r in rows(out, "sends.csv") if r["channel_id"] == "0"]
    burst = [r for r in sends if r["interval_ms"] and float(r["interval_ms"]) < 5]
    assert len(burst) >= 10
    assert len({r["virtual_time_s"] for r in burst}) == 1


def test_terminal_event_is_consumed_once(tmp_path):
    out = tmp_path / "repeated"
    counters = run(out, "--duration", "0.54")
    renders = [r for r in rows(out, "renders.csv")
               if r["channel_id"] == "0" and r["onset_consumed"] == "1"]
    assert len(renders) == 1  # Phase 2: event consumption is independent of repeated latest reads.
    assert len({r["sequence"] for r in renders}) == 1
    assert counters["publications"]["normal"]["repeat_reads"] > 0


def test_timestamped_early_renders_use_play_time_and_send_uses_due_tick(references):
    out, counters = references["timestamped", 30]
    rendered = [r for r in rows(out, "renders.csv") if r["channel_id"] == "0"]
    assert rendered
    for render in rendered:
        assert float(render["render_argument_s"]) == pytest.approx(
            float(render["play_time_s"]), abs=1 / 60)
        assert float(render["schedule_target_s"]) == pytest.approx(
            float(render["play_time_s"]), abs=1e-6)
    by_id = {r["render_id"]: r for r in rendered}
    for send in rows(out, "sends.csv"):
        error = float(send["virtual_time_s"]) - float(by_id[send["scene_id"]]["play_time_s"])
        assert -1e-6 <= error <= 1 / 30 + 1e-6
    # Current scheduler coalesces due scenes; it does not send every publication.
    assert counters["sends"] < len(rendered)


@pytest.mark.parametrize("value", [0, .5, 1, .5 + 1 / 1024, .5 + 1 / 2048, 1 / 65535])
def test_virtual_output_matches_actual_hue_dependency_wire_bytes(value):
    colour = Colour(value, value, value)
    command = LightColorCommand(channel_id=0, **dict(zip(
        ("red", "green", "blue"), colour.to_16bit(), strict=True)))
    # Exercise only the dependency's pure encoder. No socket or session is constructed.
    stub = SimpleNamespace(_sequence=0, _area_uuid_bytes=b"0" * 36)
    wire = HueDtlsStreamer._build_huestream_message(stub, [command])
    assert wire[14] == 0x00
    assert tuple(wire[-6::2]) == wire_rgb(colour)
    output = TraceOutput(load_room(ROOM))
    output.send(UniformScene(colour), 0)
    assert tuple(output.rows[0][k] for k in ("r8", "g8", "b8")) == tuple(wire[-6::2])


def test_fixture_generation_is_reproducible_small_and_antiphase(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/make_fixtures.py"),
                             "--out", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert hashes(tmp_path) == hashes(FIXTURES)
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) < 10_000_000
    with wave.open(str(tmp_path / "anti-phase.wav")) as stream:
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").reshape(-1, 2)
    assert np.array_equal(pcm[:, 0], -pcm[:, 1])


@pytest.mark.parametrize("method", ["combined", "multiband", "superflux"])
def test_observers_do_not_change_acceptance_dsp_and_band_ids(tmp_path, method):
    sys.path.insert(0, str(ROOT / "scripts"))
    from replay_chain import Replay, decode, parser
    from run_acceptance import _OfflineSource

    from lampastream.canonicalizer import AnalysisPcmFrame
    from lampastream.player_manager import _make_canonical_pipeline

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"analyser": {"onset_method": method}}))
    args = parser().parse_args(["--diagnostic-onsets",
            "--input", str(FIXTURES / "clicks-120.wav"),
        "--config", str(config), "--duration", "1", "--out", str(tmp_path / "trace")])
    replay = Replay(args)
    pcm, rate, _ = decode(args.input, duration=1)
    replay.analyse(pcm, rate)
    plain = _make_canonical_pipeline(_OfflineSource(), replay.high)
    records = []
    for start in range(0, len(pcm), 480):
        stereo = np.repeat(pcm[start:start + 480], 2, axis=1)
        records.extend(plain.feed(AnalysisPcmFrame(stereo, start, "replay-0001", "replay", False)))
    records.extend(plain.end_of_stream())
    for actual, expected in zip(replay.records, records, strict=True):
        assert actual.sample_pos == expected.sample_pos
        assert actual.sample_end == expected.sample_end
        for key in ("bars", "onset", "onset_strength", "onset_bass", "onset_mid", "onset_treble"):
            assert getattr(actual.features, key) == getattr(expected.features, key)
    if method == "multiband":
        for band in ("bass", "mid", "treble"):
            assert any(r[f"event_id_{band}"] for r in replay.features)
    replay.pipeline.stop()
    plain.stop()


def test_delivery_cap_room_and_compact_api_fields(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"analyser": {}, "energy_profile": {
        "energy_source": "peak_envelope", "peak_envelope_auto": False,
        "peak_attack_s": .1, "peak_release_s": 1.0},
        "high_effect": {"id": "custom", "effect_type": "flashes"},
        "low_effect": {"effect_type": "none"}}))
    out = tmp_path / "trace"
    counters = run(out, "--duration", ".8", "--route", "timestamped",
                   "--publications-per-tick", "3", config=config)
    energy = rows(out, "energy.csv")
    assert max(len(json.loads(r["delivered_sequences"])) for r in energy) == 3
    assert all(r["energy_source"] == "peak_envelope" for r in energy)
    # Phase 2: the one Beat-only publication bypasses continuous rendering.
    assert counters["publications"]["timestamped"]["skipped"] == 1


def test_subwindow_wav_still_has_complete_empty_trace_headers(tmp_path):
    out = tmp_path / "short"
    counters = run(out, "--duration", ".001")
    assert counters["publications"]["normal"]["published"] == 0
    assert rows(out, "features.csv") == []
    assert "candidate_sample_all" in (out / "features.csv").read_text().splitlines()[0]
    assert "onset_consumed" in (out / "renders.csv").read_text().splitlines()[0]
    assert "interval_ms" in (out / "sends.csv").read_text().splitlines()[0]
