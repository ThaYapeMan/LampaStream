#!/usr/bin/env python3
"""Generate redistributable synthetic replay audio; never reads private music."""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lampastream.backup import export_configuration  # noqa: E402
from lampastream.models import (  # noqa: E402
    Analyser,
    Controller,
    Coupling,
    Effect,
    EnergyProfile,
    VirtualPlayer,
    Zone,
)
from lampastream.storage import Storage  # noqa: E402

REFERENCE_COMMIT = "562e82e684ac86dc7cd5e706197dc8fec70b63d9"


def json_file(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


def clicks(rate, bpm=120, seconds=10):
    # Start after picker warmup; avoid a click at the truncation boundary.
    positions = [round((0.5 + n * 60 / bpm) * rate)
                 for n in range(100) if 0.5 + n * 60 / bpm < seconds - 0.01]
    samples = np.zeros(round(seconds * rate), dtype=np.float64)
    k = np.arange(round(rate * .006))
    click = .8 * np.exp(-k / (rate * .001)) * np.where(k % 2, -1., 1.)
    for pos in positions:
        count = min(len(click), len(samples) - pos)
        samples[pos:pos + count] += click[:count]
    return samples, positions


def pink(rate, seconds, seed=20261024):
    """Voss-McCartney rows with deterministic stdlib PRNG, plus white noise."""
    rng = random.Random(seed)
    rows = [rng.uniform(-1, 1) for _ in range(12)]
    samples = []
    for index in range(1, round(rate * seconds) + 1):
        row = min(11, (index & -index).bit_length() - 1)
        rows[row] = rng.uniform(-1, 1)
        samples.append(sum(rows) + rng.uniform(-1, 1))
    result = np.asarray(samples)
    return result / max(np.abs(result)) * .5


def write_fixture(out, name, pcm, rate, bits, events, description):
    pcm = pcm[:, None] if pcm.ndim == 1 else pcm
    scale = 2 ** (bits - 1)
    integers = np.rint(np.clip(pcm, -1, 1 - 1 / scale) * scale).astype(np.int32)
    if bits == 24:
        raw = np.stack([(integers >> shift) & 255 for shift in (0, 8, 16)], axis=-1)
        raw = raw.astype(np.uint8).tobytes()
    else:
        raw = integers.astype("<i2").tobytes()
    with wave.open(str(out / f"{name}.wav"), "wb") as stream:
        stream.setparams((pcm.shape[1], bits // 8, rate, 0, "NONE", "not compressed"))
        stream.writeframes(raw)
    json_file(out / f"{name}.json", {"fixture_version": 1, "sample_rate": rate,
        "channels": pcm.shape[1], "bits": bits, "frames": len(pcm),
        "event_samples": events, "description": description})


def default_export(path):
    """Export fresh local Storage after adding a playable default-model coupling."""
    with tempfile.TemporaryDirectory(prefix="replay-config-") as tmp:
        store = Storage(Path(tmp) / "config.json")
        data = store.read_configuration()
        entities = {
            "controllers": Controller(id="controller", name="Virtual output"),
            "virtual_players": VirtualPlayer(id="player", player_name="Replay"),
            "zones": Zone(id="zone", controller_id="controller", light_count=2),
            "analysers": Analyser(id="analyser"),
            "effects": Effect(id="high"),
            "energy_profiles": EnergyProfile(id="energy", high_energy_effect_id="high"),
            "couplings": Coupling(id="coupling", player_id="player", zone_id="zone",
                                  analyser_id="analyser", energy_profile_id="energy"),
        }
        for collection, entity in entities.items():
            data[collection] = [entity.to_dict()]
        store._write(data)
        exported = export_configuration(store)
        # Canonical provenance for this synthetic export, not the local wall clock.
        exported["created_at"] = "2026-10-24T00:00:00Z"
        exported["lampastream_commit"] = REFERENCE_COMMIT
        json_file(path, exported)


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    for bpm in (120, 128, 174):
        pcm, events = clicks(48000, bpm)
        write_fixture(out, f"clicks-{bpm}", pcm, 48000, 24, events,
                      f"{bpm} BPM, centre-panned mono clicks, 10 s")
    impulse = np.zeros(6 * 48000)
    impulse[5 * 48000] = .8
    write_fixture(out, "impulse", impulse, 48000, 16, [240000], "Single impulse at 5.000 s")
    t = np.arange(8 * 48000) / 48000
    levels = np.repeat(10 ** (np.array([-30, -20, -10, -3]) / 20), 2 * 48000)
    write_fixture(out, "tone-steps", np.sin(2 * np.pi * 1000 * t) * levels,
                  48000, 16, [0, 96000, 192000, 288000],
                  "1 kHz sine peak amplitudes -30/-20/-10/-3 dBFS, 2 s each")
    # These 24 kHz fixtures exercise production resampling and keep the set <10 MB.
    rate = 24000
    t = np.arange(20 * rate) / rate
    log_ratio = np.log(10000 / 20)
    phase = 2 * np.pi * 20 * 20 / log_ratio * np.expm1(t / 20 * log_ratio)
    write_fixture(out, "sweep", .5 * np.sin(phase), rate, 16, [],
                  "20 s logarithmic sine sweep, 20 Hz to 10 kHz")
    write_fixture(out, "pink-noise", pink(rate, 5), rate, 16, [],
                  "5 s Voss-McCartney pink noise; seed 20261024; no sparse event labels")
    write_fixture(out, "silence", np.zeros(3 * 48000), 48000, 16, [], "3 s digital silence")
    pcm, events = clicks(rate)
    write_fixture(out, "anti-phase", np.column_stack((pcm, -pcm)), rate, 16, events,
                  "120 BPM stereo clicks; L=-R exactly after PCM quantization")
    pan = np.linspace(0, 1, len(pcm))
    write_fixture(out, "panning", np.column_stack((pcm * (1 - pan), pcm * pan)),
                  rate, 16, events, "120 BPM clicks panning linearly left to right over 10 s")
    default_export(out / "default-config.json")
    total = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    if total >= 10_000_000:
        raise ValueError(f"Fixture set exceeds 10 MB: {total}")
    print(f"Generated 10 WAV fixtures, sidecars and default export: {total} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "tests/fixtures/replay")
    generate(parser.parse_args().out)
