#!/usr/bin/env python3
"""Offline BEAT-01 evidence. Never starts players, workers or light drivers."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from replay_chain import ROOT, Replay, decode, parser


def measure(path, out, *, route='normal', room='two-channel.json'):
    args = parser().parse_args(['--input', str(path), '--config',
        str(ROOT/'tests/fixtures/replay/default-config.json'), '--route', route,
        '--room', str(ROOT/'tests/fixtures/rooms'/room), '--out', str(out)])
    replay = Replay(args)
    try:
        pcm, rate, fmt = decode(path)
        started = time.process_time()
        replay.analyse(pcm, rate)
        cpu = time.process_time()-started
        asyncio.run(replay.run())
        counters = replay.save(fmt)
        events = [r['event'] for r in replay.engine.event_records.values()]
        beats = [e for e in events if e.kind == 'beat']
        confirmed = [e for e in beats if not e.predicted]
        textures = [e for e in events if e.kind == 'onset']
        seconds = replay.sample_count/48000
        sidecar = path.with_suffix('.json')
        truth = json.loads(sidecar.read_text()) if sidecar.exists() else {}
        kicks = truth.get('instruments', {}).get('kick', truth.get('event_samples', []))
        hits = sum(any(abs(e.candidate_sample-k) <= 480 for e in confirmed) for k in kicks)
        matched = [e for e in confirmed if any(abs(e.candidate_sample-k) <= 480 for k in kicks)]
        stable = [(r.sample_pos/48000, r.features.tempo_bpm) for r in replay.records
                  if r.features.tempo_locked]
        latest = next((r.features for r in reversed(replay.records)
                       if r.features.tempo_bpm is not None), None)
        diagnostics = {e.id for r in replay.records for e in r.features.diagnostic_events}
        ratio = sum(e.on_beat for e in matched)/len(matched) if matched else None
        # Each channel/render is sampled equally at the controlled cadence.
        # Threshold is relative to that frame's own base colour in linear light.
        from lampastream.accent import _linear
        duty = {}
        for row in replay.renders:
            channel = row['channel_id']
            pre = max(_linear(row[f'pre_{c}']) for c in 'rgb')
            post = max(_linear(row[f'post_{c}']) for c in 'rgb')
            duty.setdefault(channel, []).append(post > .7*pre+1e-9)
        latency = counters['latency'][route]['first_send_ms']
        return dict(fixture=path.stem, duration_s=seconds,
            before_events_s=len(diagnostics)/seconds, beat_events_s=len(beats)/seconds,
            texture_events_s=len(textures)/seconds, confirmed_beats=len(confirmed),
            predicted_beats=len(beats)-len(confirmed), kick_hits=hits, kicks=len(kicks),
            kick_recall=hits/len(kicks) if kicks else None,
            false_triggers=len(confirmed)-len(matched),
            bpm=latest.tempo_bpm if latest else None,
            alt_bpm=latest.tempo_alt_bpm if latest else None,
            lock_s=stable[0][0] if stable else None, on_beat_ratio=ratio,
            duty_cycle={key: sum(values)/len(values) for key, values in duty.items()},
            latency_median_ms=latency['median'] if latency else None,
            cpu_ms_hop=cpu/seconds*10,
            event_loss=counters['events']['all']['lost'])
    finally:
        replay.pipeline.stop()


def main():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument('--out', type=Path, default=ROOT/'docs/baseline/traces-phase5')
    args = command.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted((ROOT/'tests/fixtures/replay/beats').glob('*.wav')):
        result = measure(path, args.out/path.stem)
        rows.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    (args.out/'measurements.json').write_text(json.dumps(rows, indent=2, sort_keys=True)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
