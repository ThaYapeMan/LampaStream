# Baseline evidence and regeneration

Per-fixture committed evidence is counters.json, meta.json, latency.csv, events.csv
and determinism hash files. Bulk energy.csv, features.csv, renders.csv and sends.csv
are generated locally and ignored here. Keep aggregate measurements and reports.

From the repository root, regenerate a complete trace into a temporary directory:

```sh
.venv/bin/python scripts/replay_chain.py \
  --input tests/fixtures/replay/clicks-120.wav \
  --config tests/fixtures/replay/default-config.json \
  --route normal --render-hz 30 --seed 0 --out /tmp/replay-normal
# Timestamped playback with simulated 1.5-second lookahead:
.venv/bin/python scripts/replay_chain.py \
  --input tests/fixtures/replay/clicks-120.wav \
  --config tests/fixtures/replay/default-config.json \
  --route timestamped --lead-s 1.5 --out /tmp/replay-timestamped
```

Replace the input with any fixture under tests/fixtures/replay/ (including beats/)
and preserve the original route, configuration, room, rate, seed and other options
from the kept meta.json and phase notes. Use `--help` for all harness options.
To reproduce historical byte hashes, use the phase's recorded implementation
revision in a separate checkout; current code intentionally differs from older
phases. Do not replace tests/fixtures/ pins with newly generated expectations.
See [testing](../testing.md#replay-chain-and-trace-format) for the complete generated
trace schema and [baseline](../baseline.md) for phase measurements.
