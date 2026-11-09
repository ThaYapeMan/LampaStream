#!/usr/bin/env python3
"""Analyse local reference audio and score grids/replay sends without live sources."""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from lampastream.grid.analyser import analyse, decode, low_band_attacks  # noqa: E402

BREAKS = ((210, 212), (240, 242), (261, 262), (270, 272))


def score(reference, observed, tolerances):
    delta = (abs(reference[:, None]-observed[None, :]).min(axis=1)
             if len(observed) else np.full(len(reference), np.inf))
    return {'reference_beats': len(reference),
            **{f'hits_{ms}ms': int(sum(delta <= ms/1000)) for ms in tolerances}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--replay-events', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    raw = args.input.read_bytes()
    grid = analyse(raw)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'grid.json').write_text(json.dumps(grid.to_dict(), indent=2)+'\n')
    result = dict(file=args.input.name, sha256=grid.file_sha256, sample_rate=grid.sample_rate,
                  duration=grid.duration, timing_basis=grid.timing_basis, tempo=grid.tempo,
                  confidence=grid.confidence, beats=len(grid.beats), kicks=sum(grid.kick_flags),
                  analysis_seconds=time.monotonic()-started,
                  sections=[s.__dict__ for s in grid.sections])
    if args.reference:
        times = np.genfromtxt(args.reference, delimiter=',', names=True)['time_s']
        keep = np.ones(len(times), bool)
        for start, end in BREAKS:
            keep &= ~((times >= start) & (times < end))
        reference = times[keep]
        y, sr, _ = decode(raw)
        energy, hop, threshold = low_band_attacks(y, sr)
        values = []
        for stamp in times:
            lo = max(0, round((stamp-.07)*sr/hop))
            hi = min(len(energy), round((stamp+.07)*sr/hop)+1)
            values.append(float(np.max(energy[lo:hi])))
        kick_mask = np.asarray(values) >= threshold
        kick_reference = times[kick_mask]
        result['reference_classification'] = dict(
            total=len(times), kick_bearing=int(sum(kick_mask)),
            kickless=int(sum(~kick_mask)), threshold=threshold,
            basis='same low-band gate evaluated independently at CSV positions')
        result['csv_reference'] = score(reference, np.array(grid.beats), (10, 15, 50))
        beats = np.array(grid.beats)
        kicks = beats[np.array(grid.kick_flags)]
        result['kick_events'] = score(kick_reference, kicks, (10, 15, 50))
        result['kick_reference_times'] = list(map(float, kick_reference))
        result['kickless_reference_times'] = list(map(float, times[~kick_mask]))
        # Separately label the owner's rigid first-kick coordinate; never relabel the CSV.
        rigid = .499+np.arange(len(times))*(60/128)
        rigid = rigid[rigid < grid.duration]
        rigid_keep = np.ones(len(rigid), bool)
        for start, end in BREAKS:
            rigid_keep &= ~((rigid >= start) & (rigid < end))
        result['owner_rigid_reference'] = score(rigid[rigid_keep], beats, (10, 15, 50))
        result['grid_accents_in_breaks'] = [int(sum((kicks >= a) & (kicks < b)))
                                           for a, b in BREAKS]
        if args.replay_events:
            rows = list(csv.DictReader(args.replay_events.open()))
            for column in ('candidate_sample', 'first_render_over_half_s', 'first_send_s'):
                values = np.array([float(r[column])/(48000 if column == 'candidate_sample' else 1)
                                   for r in rows if r[column]])
                result['replay_'+column] = {
                    **score(kick_reference, values, (10, 50)),
                    'accents_in_breaks': [int(sum((values >= a) & (values < b)))
                                          for a, b in BREAKS]}
    (args.out/'bench.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
