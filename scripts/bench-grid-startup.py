#!/usr/bin/env python3
"""Measure loopback cold-grid stages and replay causal arrivals through the full chain."""
import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
from fake_lms_library import Session  # noqa: E402
from replay_chain import Replay, parser  # noqa: E402

from lampastream.grid.analyser import decode  # noqa: E402
from lampastream.grid.cache import GridCache  # noqa: E402
from lampastream.lms_grid import LmsGridAdapter  # noqa: E402


async def acquire(path, out, duration):
    async with Session(path, duration=duration) as session:
        adapter = LmsGridAdapter('127.0.0.1', session.web_port, GridCache(out/'cache'))
        adapter.select('44436', path.stat().st_size, duration=duration)
        head, full = None, None
        started = time.monotonic()
        try:
            async with asyncio.timeout(240):
                while adapter.state != 'ready':
                    if adapter.grid and adapter.grid.provisional and head is None:
                        head = adapter.grid
                    if adapter.state == 'failed':
                        raise RuntimeError('Grid acquisition failed')
                    await asyncio.sleep(.001)
            full = adapter.grid
            stages = list(adapter.stages)
            if head:
                (out/'head.json').write_text(json.dumps(head.to_dict()))
            (out/'full.json').write_text(json.dumps(full.to_dict()))
            return (head, full, stages, time.monotonic()-started,
                    list(session.requests), session.ranges)
        finally:
            await adapter.close()


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--input', type=Path, required=True)
    arguments.add_argument('--out', type=Path, required=True)
    args = arguments.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    pcm, rate, _ = decode(args.input.read_bytes())
    head, full, stages, elapsed, requests, ranges = asyncio.run(acquire(
        args.input, args.out, len(pcm)/rate))
    head_at = next((s['since_start_s'] for s in stages if s['stage'].startswith('head')), None)
    full_at = next(s['since_start_s'] for s in stages if s['stage'] in ('full', 'cache-hit'))
    replay_args = parser().parse_args([
        '--input', str(args.input), '--config',
        str(ROOT/'tests/fixtures/replay/default-config.json'),
        '--route', 'normal', '--out', str(args.out/'replay')])
    replay = Replay(replay_args)

    def provider(frame):
        position = frame.sample_pos/48000
        grid = full if position >= full_at else head if head_at and position >= head_at else None
        state = 'ready' if grid is full else 'fetching'
        return 'cold-start', grid, 0., dict(grid_fetch_state=state)

    replay.pipeline._beat_fusion.grid_provider = provider
    tracker_lock = []
    feed = replay.pipeline.feed

    def observed(frame):
        records = feed(frame)
        if replay.pipeline._beat_fusion.clock.locked and not tracker_lock:
            tracker_lock.append(frame.sample_pos/48000)
        return records

    replay.pipeline.feed = observed
    try:
        import numpy as np
        replay.analyse(np.repeat(pcm[:, None], 2, axis=1), rate)
        asyncio.run(replay.run())
        replay.save({'sample_rate': rate, 'channels': 1})
        accents = sorted(data['first_send_s'] for data in replay.engine.event_records.values()
                         if data.get('first_send_s') is not None)
        grid_accents = [data['first_send_s']
                        for identity, data in replay.engine.event_records.items()
                        if identity[1] == 'grid' and data.get('first_send_s') is not None]
        first_grid_accent = min(grid_accents) if grid_accents else None
        until = first_grid_accent if first_grid_accent is not None else full_at
        opening = [0., *[stamp for stamp in accents if 0 <= stamp <= until], until]
        dark = max((b-a for a, b in zip(opening, opening[1:], strict=False)), default=until)
        grid_active = next((stamp/48000 for record, stamp in zip(
            replay.records, replay.availability, strict=True)
                            if record.features.beat_source == 'grid'), None)
        full_active = next((stamp/48000 for record, stamp in zip(
            replay.records, replay.availability, strict=True)
                            if record.features.beat_source == 'grid'
                            and not record.features.provisional), None)
        result = dict(file=args.input.name, first_accent_s=accents[0] if accents else None,
                      tracker_lock_s=tracker_lock[0] if tracker_lock else None,
                      provisional_grid_s=head_at, provisional_adopted_s=grid_active,
                      first_grid_accent_s=first_grid_accent,
                      full_grid_s=full_at, full_adopted_s=full_active,
                      max_opening_dark_s=dark, acquisition_wall_s=elapsed,
                      head_tempo=head.tempo if head else None, full_tempo=full.tempo,
                      stages=stages, requests=requests, ranges=ranges)
        (args.out/'timeline.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, indent=2))
        assert result['first_accent_s'] is not None and result['first_accent_s'] < 3
        assert dark <= 1.5
        if head_at is not None:
            assert head_at < 3, f'Loopback head exceeded target: {head_at:.3f}s'
    finally:
        replay.pipeline.stop()


if __name__ == '__main__':
    main()
