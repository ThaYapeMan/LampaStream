"""Session replay artifacts shared safely by xdist workers, never expected pins."""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import pickle
import subprocess

from replay_chain import ROOT, Replay, decode


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class DiskReplays:
    def __init__(self, base):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.tree = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD:src'], cwd=ROOT, text=True).strip()
        # Also fence local edits during development, before their commit exists.
        self.source = sha(b''.join(p.read_bytes() for p in
                                  sorted((ROOT/'src/lampastream').glob('*.py'))))
        self.revision = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        self.harness = sha((ROOT/'scripts/replay_chain.py').read_bytes())

    def run(self, args):
        options = {k: v for k, v in vars(args).items()
                   if k not in {'out', 'input', 'config', 'room'}}
        config = sha(args.config.read_bytes())
        source = sha(args.input.read_bytes())
        common = [source, config, self.tree, self.source, self.revision, self.harness,
                  sha(args.room.read_bytes())]
        key = sha(json.dumps([common, options], sort_keys=True).encode())
        out = self.base/key
        with (self.base/f'{key}.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (out/'meta.json').exists():
                return out
            args.out = out
            replay = Replay(args)
            analysis_key = sha(json.dumps([common, args.start, args.duration,
                                          args.lead_s], sort_keys=True).encode())
            analysis = self.base/f'{analysis_key}.pickle'
            try:
                with (self.base/f'{analysis_key}.analysis.lock').open('w') as analysis_lock:
                    fcntl.flock(analysis_lock, fcntl.LOCK_EX)
                    if analysis.exists():
                        with analysis.open('rb') as stream:
                            (replay.records, replay.features, replay.availability,
                             replay.sample_count, fmt) = pickle.load(stream)
                    else:
                        pcm, rate, fmt = decode(args.input, args.start, args.duration)
                        replay.analyse(pcm, rate)
                        with analysis.open('wb') as stream:
                            pickle.dump((replay.records, replay.features, replay.availability,
                                         replay.sample_count, fmt), stream,
                                        protocol=pickle.HIGHEST_PROTOCOL)
                asyncio.run(replay.run())
                channels = (args.input.stem == "clicks-120" and
                            args.publications_per_tick == 0)
                replay.save(fmt, write_channel_traces=channels)
            finally:
                replay.pipeline.stop()
        return out
