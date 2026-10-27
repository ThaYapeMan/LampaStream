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


def generate_beats(out):
    """Twelve-second drum loops with independent instrument/grid truth."""
    out.mkdir(parents=True, exist_ok=True)
    rate, seconds = 48000, 12
    rng = np.random.default_rng(20261027)
    names = [('house', 120), ('techno', 128), ('breakbeat', 174),
             ('disco', 100), ('deep-house', 122), ('pad-texture', 120),
             ('tempo-change', 120), ('breakdown', 120)]
    for name, bpm in names:
        t = np.arange(rate*seconds)/rate
        pad = .015*(np.sin(2*np.pi*330*t)+.5*np.sin(2*np.pi*440*t))
        # Smooth onset/ending: no artificial transient in the zero-beat control.
        pad *= np.minimum(1, t/.5)*np.minimum(1, (seconds-t)/.5)
        pcm = pad.copy()
        beat_times = []
        stamp = .5
        while stamp < seconds-.05:
            beat_times.append(stamp)
            stamp += 60/(128 if name == 'tempo-change' and stamp >= 6 else bpm)
        if name == 'tempo-change':
            beat_times = [v for v in beat_times if v < 6]
            stamp = 6.
            while stamp < seconds-.05:
                beat_times.append(stamp)
                stamp += 60/128
        truth = dict(kick=[], snare=[], hat=[], beats=[], downbeats=[])
        def strike(stamp, audio, instrument, pcm=pcm, truth=truth):
            pos = round(stamp*rate)
            count = min(len(audio), len(pcm)-pos)
            if count > 0:
                pcm[pos:pos+count] += audio[:count]
                truth[instrument].append(pos)
        k = np.arange(round(.16*rate))/rate
        kick = .65*np.sin(2*np.pi*(58*k+45*.018*(1-np.exp(-k/.018))))
        kick *= (1-np.exp(-k/.001))*np.exp(-k/.035)
        h = np.arange(round(.035*rate))/rate
        noise = rng.normal(size=len(h))
        hat = .045*(noise-np.roll(noise, 1))*np.exp(-h/.006)
        sn = np.arange(round(.12*rate))/rate
        snare = .15*rng.normal(size=len(sn))*np.exp(-sn/.018)
        for i, stamp in enumerate(beat_times):
            truth['beats'].append(round(stamp*rate))
            if i % 4 == 0:
                truth['downbeats'].append(round(stamp*rate))
            if name != 'pad-texture':
                if not (name == 'breakdown' and 4 <= stamp < 8):
                    if name != 'breakbeat' or i % 2 == 0:
                        strike(stamp, kick, 'kick')
                if i % 2 == 1:
                    strike(stamp, snare, 'snare')
                divisions = 4 if name in ('techno', 'breakbeat') else 2
                for j in range(divisions):
                    strike(stamp+j*60/bpm/divisions,
                           hat*(10**(-30/20) if name == 'deep-house' else 1), 'hat')
        if name == 'techno':
            envelope = np.clip((t-7.5)/4, 0, 1)
            noise = rng.normal(size=len(t))
            pcm += .025*envelope*(noise-np.roll(noise, 1))
        if name == 'disco':
            pcm += .04*np.sin(2*np.pi*110*t)*(np.sin(2*np.pi*bpm/60*t) > 0)
        if name == 'deep-house':
            pcm *= 10**(-18/20)/max(abs(pcm))
        if name == 'pad-texture':
            truth['beats'] = truth['downbeats'] = []
        write_fixture(out, name, pcm, rate, 16, truth['kick'], name+' synthetic loop')
        path = out/f'{name}.json'
        sidecar = json.loads(path.read_text())
        sidecar.update(fixture_version=2, bpm=None if name == 'pad-texture' else bpm,
                       first_beat_sample=24000 if name != 'pad-texture' else None,
                       quantum=4, instruments=truth,
                       tempo_changes=[dict(sample=6*rate, bpm=128)]
                       if name == 'tempo-change' else [])
        json_file(path, sidecar)
    total = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    if total >= 15_000_000:
        raise ValueError(f'Beat fixture set exceeds 15 MB: {total}')
    print(f'Generated eight BEAT-01 fixtures: {total} bytes')


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
    parser.add_argument('--beats', action='store_true')
    args = parser.parse_args()
    (generate_beats if args.beats else generate)(args.out)
