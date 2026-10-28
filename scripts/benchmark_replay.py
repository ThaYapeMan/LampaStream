#!/usr/bin/env python3
"""Measure one-core replay execution cost, excluding CSV export and physical I/O.

Virtual backlog/drop counters describe the harness, not an OS scheduling model.
Run with OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 and --cpu for affinity.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from bisect import bisect_right
from pathlib import Path

import numpy as np
from replay_chain import RATE, ROOT, Replay, decode, parser


def benchmark(fixture, route, hz):
    args = parser().parse_args([
        '--input', str(ROOT/f'tests/fixtures/replay/{fixture}.wav'),
        '--config', str(ROOT/'tests/fixtures/replay/default-config.json'),
        '--route', route, '--render-hz', str(hz), '--out', '/tmp/replay-benchmark-unused'])
    replay = Replay(args)
    try:
        pcm, rate, _ = decode(args.input)
        started = time.process_time()
        replay.analyse(pcm, rate)
        analysis_cpu = time.process_time()-started
        durations = []
        backlog = 0
        finish = replay.finish_tick
        previous = time.perf_counter()

        def observe(engine):
            nonlocal previous, backlog
            now = time.perf_counter()
            durations.append((now-previous)*1000)
            backlog = max(backlog, bisect_right(replay.availability,
                          (replay.now+1e-10)*RATE)-replay.cursor)
            finish(engine)
            previous = time.perf_counter()

        replay.finish_tick = observe
        started = time.process_time()
        asyncio.run(replay.run())
        loop_cpu = time.process_time()-started
        counters = replay.counters()
        duration = replay.sample_count/RATE
        fraction = (analysis_cpu+loop_cpu)/duration
        return (f'| {fixture} | {route} | {hz} | {analysis_cpu/duration*10:.3f} | '
                f'{np.percentile(durations, 95):.3f} / {max(durations):.3f} | '
                f'{fraction*100:.1f} | {1/fraction:.2f}× | {backlog} | '
                f'{counters["publication_queue_drops"]} / {counters["event_queue_drops"]} |')
    finally:
        replay.pipeline.stop()


def benchmark_clock():
    from lampastream.tempo_clock import TempoClock

    clock = TempoClock()
    started = time.process_time()
    for index in range(10000):
        clock.update(index*.1)
    update_us = (time.process_time()-started)*1e6/10000
    clock = TempoClock()
    started = time.process_time()
    for index in range(10000):
        clock.trigger(index*.5)
    trigger_us = (time.process_time()-started)*1e6/10000
    return f'Clock update: {update_us:.3f} µs; trigger/hypothesis update: {trigger_us:.3f} µs.'


def main():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument('--cpu', type=int)
    command.add_argument('--out', type=Path)
    args = command.parse_args()
    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})
    rows = [f'Affinity: {sorted(os.sched_getaffinity(0))}', '',
        '| Fixture | Route | Hz | DSP CPU ms/hop | Loop p95 / max ms | Core % | Margin | '
        'Virtual backlog | Pub / event drops |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for fixture in ('pink-noise', 'clicks-174'):
        for route in ('normal', 'timestamped'):
            for hz in (30, 50, 60):
                row = benchmark(fixture, route, hz)
                rows.append(row)
                print(row, flush=True)
    rows += ["", benchmark_clock()]
    print(rows[-1], flush=True)
    if args.out:
        args.out.write_text('\n'.join(rows)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
