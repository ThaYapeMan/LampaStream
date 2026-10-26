"""Shared in-process replay cache and explicit numeric regression measurements."""
from __future__ import annotations

import csv
import json
import os
from functools import cache
from pathlib import Path

import numpy as np
import pytest
from replay_cache_support import DiskReplays
from replay_chain import parser

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/replay"
NUMBERS = ROOT / "tests/fixtures/onset-regression-numbers.json"
HOP = 480
BANDS = ("all", "bass", "mid", "treble")
CLICK_FIXTURES = ("clicks-120", "clicks-128", "clicks-174", "panning", "anti-phase")
POSITION_FIXTURES = ("clicks-120", "clicks-128", "clicks-174", "impulse", "panning")


@cache
def expected(section):
    return json.loads(NUMBERS.read_text())[section]


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


class ReplayCache:
    """Analyze once per fixture/method; replay fresh production publication/mixer state.

    Config and PCM never change across route/rate/delivery variants. Deep copies
    isolate mutable publication features/trace rows; every run constructs and
    closes its own pipeline and output. No production or BENCH-01 code is patched.
    """

    def __init__(self, base):
        self.base = base
        self.disk = DiskReplays(base)
        self.outputs = {}

    def get(self, fixture, route="normal", hz=30, cap=0, method="combined"):
        key = (fixture, route, hz, cap, method)
        if key in self.outputs:
            return self.outputs[key]
        config = FIXTURES / "default-config.json"
        if method != "combined":
            config = self.base / f"{method}-{os.getpid()}.json"
            if not config.exists():
                data = json.loads((FIXTURES / "default-config.json").read_text())
                data["configuration"]["analysers"][0]["onset_method"] = method
                config.write_text(json.dumps(data, sort_keys=True))
        out = self.base / "-".join(map(str, key))
        args = parser().parse_args(["--input", str(FIXTURES / f"{fixture}.wav"),
            "--config", str(config), "--route", route, "--render-hz", str(hz),
            "--publications-per-tick", str(cap), "--seed", "0", "--out", str(out)])
        out = self.disk.run(args)
        counters = json.loads((out / "counters.json").read_text())
        result = {"out": out, "features": [{k:v for k,v in row.items()
                                if k in {"sequence", "availability_sample"}
                                or any(k.startswith(prefix) for prefix in (
                                    "event_id_", "candidate_sample_", "candidate_strength_",
                                    "reported_strength_"))}
                               for row in read_csv(out / "features.csv")],
                  "energy": [{"consumed_sequences": r["consumed_sequences"]}
                             for r in read_csv(out / "energy.csv")], "counters": counters,
                  "events": read_csv(out / "events.csv"), "truth": truth(fixture)}
        self.outputs[key] = result
        return result


@pytest.fixture(scope="session")
def regression_replays(replay_cache):
    """One disk-backed session cache, including all xdist workers."""
    return replay_cache


def truth(fixture):
    data = json.loads((FIXTURES / f"{fixture}.json").read_text())
    return np.asarray(data["event_samples"], dtype=np.int64) * 48000 // data["sample_rate"]


def events(replay, band="all"):
    return [row for row in replay["features"] if row[f"event_id_{band}"]]


def positions(replay, band="all"):
    rows, target = events(replay, band), replay["truth"]
    result = {"truth_count": len(target), "event_count": len(rows)}
    for label, field in (("availability", "availability_sample"),
                         ("candidate", f"candidate_sample_{band}")):
        found = np.array([int(row[field]) for row in rows], dtype=np.int64)
        if not len(found):
            result[label] = {"median_samples": None, "max_abs_samples": None,
                             "misses": len(target), "false_positives": 0}
            continue
        # Independent nearest neighbours, not a forced one-to-one detector match.
        differences = found[:, None] - target[None, :]
        nearest = differences[np.argmin(abs(differences), axis=0), np.arange(len(target))]
        result[label] = {"median_samples": float(np.median(nearest)),
            "max_abs_samples": int(np.max(abs(nearest))),
            "misses": int(np.sum(np.min(abs(differences), axis=0) > 2 * HOP)),
            "false_positives": int(np.sum(np.min(abs(differences), axis=1) > 2 * HOP))}
    lookahead = [int(r["availability_sample"]) - int(r[f"candidate_sample_{band}"]) for r in rows]
    result["lookahead_samples"] = sorted(set(lookahead))
    return result


def panning_halves(replay, band="all"):
    rows = events(replay, band)
    target = replay["truth"]
    halves = []
    for subset in (target[target < 5 * 48000], target[target >= 5 * 48000]):
        closest = [min(rows, key=lambda r: abs(int(r["availability_sample"]) - t)) for t in subset]
        halves.append({"events": len(closest),
            "availability_offset_median": float(np.median([
                int(r["availability_sample"]) - t for r, t in zip(closest, subset, strict=True)])),
            "candidate_offset_median": float(np.median([
                int(r[f"candidate_sample_{band}"]) - t for r, t in
                zip(closest, subset, strict=True)])),
            "candidate_strength_median": float(np.median([
                float(r[f"candidate_strength_{band}"]) for r in closest])),
            "reported_strength_median": float(np.median([
                float(r[f"reported_strength_{band}"]) for r in closest]))})
    return halves


def ranks(values):
    """Average ranks for ties, implemented solely with NumPy."""
    values = np.asarray(values, dtype=float)
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    starts = np.r_[0, np.cumsum(counts)[:-1]]
    return (starts + (counts - 1) / 2)[inverse]


def spearman(levels, strengths):
    a, b = ranks(levels), ranks(strengths)
    a, b = a - a.mean(), b - b.mean()
    denominator = np.sqrt(np.dot(a, a) * np.dot(b, b))
    return float(np.dot(a, b) / denominator) if denominator else None


def strengths(replay, band="all"):
    rows = events(replay, band)
    candidate = [float(r[f"candidate_strength_{band}"]) for r in rows]
    reported = [float(r[f"reported_strength_{band}"]) for r in rows]
    return {"candidate_samples": [int(r[f"candidate_sample_{band}"]) for r in rows],
        "candidate": candidate, "reported": reported,
        "below_tenth_fraction": float(np.mean(np.array(reported) < .1 * max(candidate)))
            if candidate else None}


def tone_levels(replay, band="all"):
    """Match a transient within 100 ms of each known amplitude step.

    Startup has no post-warmup onset. Explicitly encode its missing observation
    with presence=False and zero diagnostic strength; never invent an event ID.
    """
    rows = events(replay, band)
    present, candidate, reported = [], [], []
    for target in replay["truth"]:
        row = min(rows, key=lambda r: abs(int(r["availability_sample"]) - target)) if rows else None
        found = row is not None and abs(int(row["availability_sample"]) - target) <= 4800
        present.append(bool(found))
        candidate.append(float(row[f"candidate_strength_{band}"]) if found else 0.)
        reported.append(float(row[f"reported_strength_{band}"]) if found else 0.)
    return {"present": present, "candidate": candidate, "reported": reported,
            "rho": spearman([-30., -20., -10., -3.], reported)}


SURVIVAL_FIXTURES = (*POSITION_FIXTURES, "anti-phase", "tone-steps")
EVENT_FIELDS = ("received", "triggered", "merged", "expired", "lost")
PUBLICATION_FIELDS = ("consumed", "skipped", "repeated")


def skipped_flags(replay, band="all"):
    consumed = {seq for row in replay["energy"] for seq in json.loads(row["consumed_sequences"])}
    onsets = events(replay, band)
    return {"never_consumed_flags": sum(int(r["sequence"]) not in consumed for r in onsets),
            "sole_carrier_skipped": sum(
                event["disposition"] == "received" for event in replay["events"]
                if band == "all" or band in json.loads(event["bands"]))}


def survival(replay, route):
    data = replay["counters"]
    return {"events": {band:[data["events"][band][k] for k in EVENT_FIELDS] for band in BANDS},
        "publications": [data["publications"][route][k] for k in PUBLICATION_FIELDS],
        "skipped_flags": {b:skipped_flags(replay, b) for b in BANDS}}
