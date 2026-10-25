# Phase 2 synthetic event references

Ten fixtures, both routes, default exported configuration, 30 Hz, seed 0,
unrestricted publications and the synthetic two-channel capabilities room.
Each directory contains counters.json, meta.json and events.csv. The default
flash intensity is zero: envelope carriage is software evidence, not measured light.

Phase-zero references are preserved unchanged in ../traces-phase0. Reproduce with:

```sh
.venv/bin/python scripts/replay_chain.py --input tests/fixtures/replay/FIXTURE.wav \
  --config tests/fixtures/replay/default-config.json --route ROUTE --render-hz 30 \
  --seed 0 --out /tmp/replay-FIXTURE-ROUTE
```

See ../../testing.md for the seven-file schema and event disposition definitions.
