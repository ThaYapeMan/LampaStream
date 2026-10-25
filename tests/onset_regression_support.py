"""Shared in-process replay cache and explicit numeric regression measurements."""
from __future__ import annotations

import asyncio
import copy
import csv
import json
from pathlib import Path

import numpy as np
import pytest
from replay_chain import Replay, decode, parser

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/replay"
NUMBERS = ROOT / "tests/fixtures/onset-regression-numbers.json"
HOP = 480
BANDS = ("all", "bass", "mid", "treble")
CLICK_FIXTURES = ("clicks-120", "clicks-128", "clicks-174", "panning", "anti-phase")
POSITION_FIXTURES = ("clicks-120", "clicks-128", "clicks-174", "impulse", "panning")


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
        self.analysis = {}
        self.outputs = {}

    def get(self, fixture, route="normal", hz=30, cap=0, method="combined"):
        key = (fixture, route, hz, cap, method)
        if key in self.outputs:
            return self.outputs[key]
        config = FIXTURES / "default-config.json"
        if method != "combined":
            config = self.base / f"{method}.json"
            if not config.exists():
                data = json.loads((FIXTURES / "default-config.json").read_text())
                data["configuration"]["analysers"][0]["onset_method"] = method
                config.write_text(json.dumps(data, sort_keys=True))
        out = self.base / "-".join(map(str, key))
        args = parser().parse_args(["--input", str(FIXTURES / f"{fixture}.wav"),
            "--config", str(config), "--route", route, "--render-hz", str(hz),
            "--publications-per-tick", str(cap), "--seed", "0", "--out", str(out)])
        replay = Replay(args)
        source_key = (fixture, method)
        try:
            if source_key not in self.analysis:
                pcm, rate, fmt = decode(args.input)
                replay.analyse(pcm, rate)
                self.analysis[source_key] = copy.deepcopy((replay.records, replay.features,
                    replay.availability, replay.sample_count, fmt))
            else:
                (replay.records, replay.features, replay.availability,
                 replay.sample_count, fmt) = copy.deepcopy(self.analysis[source_key])
            asyncio.run(replay.run())
            counters = replay.save(fmt)
        finally:
            replay.pipeline.stop()
        result = {"out": out, "features": read_csv(out / "features.csv"),
                  "energy": read_csv(out / "energy.csv"), "counters": counters,
                  "truth": truth(fixture)}
        self.outputs[key] = result
        return result


_CACHE = None


@pytest.fixture(scope="module")
def regression_replays(tmp_path_factory):
    """Module-scoped access, shared session cache: each parameter tuple runs once."""
    global _CACHE
    if _CACHE is None:
        _CACHE = ReplayCache(tmp_path_factory.mktemp("onset-regressions"))
    return _CACHE


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
EVENT_FIELDS = ("received", "accepted", "rendered", "merged", "expired", "lost")
PUBLICATION_FIELDS = ("consumed", "skipped", "repeated")


def skipped_flags(replay, band="all"):
    consumed = {seq for row in replay["energy"] for seq in json.loads(row["consumed_sequences"])}
    onsets = events(replay, band)
    ids = {r[f"event_id_{band}"] for r in onsets}
    surviving = {r[f"event_id_{band}"] for r in onsets if int(r["sequence"]) in consumed}
    return {"never_consumed_flags": sum(int(r["sequence"]) not in consumed for r in onsets),
            "sole_carrier_skipped": len(ids - surviving)}


def survival(replay, route):
    data = replay["counters"]
    return {"events": {band:[data["events"][band][k] for k in EVENT_FIELDS] for band in BANDS},
        "publications": [data["publications"][route][k] for k in PUBLICATION_FIELDS],
        "skipped_flags": {b:skipped_flags(replay, b) for b in BANDS}}
