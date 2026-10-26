# LAT-01 software latency evidence

Before: phase-two code at 542b9ed with the part-1 observer ledger added.
After: LAT-01 implementation, default analyser and output room, seed 0,
unrestricted delivery, 30 Hz. Each CSV row retains fixture/route/event identity,
truth coordinates, detector coordinates, first-render/send offsets and terms.
The JSON files preserve complete per-run counters and provenance metadata.
Timestamped replay playback lead is 1500 ms; positive onset_lead_s advances
light by 20 ms. Midpoint interpolation affects playback estimation only;
candidate_sample retains the detected 10 ms hop coordinate.

Reproduce a run with:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python scripts/replay_chain.py \
  --input tests/fixtures/replay/clicks-120.wav \
  --config tests/fixtures/replay/default-config.json \
  --route normal --render-hz 30 --out /tmp/lat01-clicks-120
```

The trace is software-only; it never opens a player, bridge or lamp.
