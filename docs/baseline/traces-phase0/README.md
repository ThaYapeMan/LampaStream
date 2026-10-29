# Synthetic full-chain reference traces

These BENCH-01 reference numbers use the implementation at full revision
**b36f5d97d3af2cf846208c2097e3f3ff3d1b44a3**, with the behavior comparison baseline
**3998c440f464d0cf02743633fba98e8dd990743b** unchanged. The BENCH-01 starting
revision was **562e82e684ac86dc7cd5e706197dc8fec70b63d9**. Existing production
behavior is retained, including normal-route flag loss/reuse, shrink bursts,
render-call envelope ballistics and timestamped due-scene coalescing.

There are ten fixtures × two routes, each with counters.json and meta.json.
Every run uses `tests/fixtures/replay/default-config.json`, the synthetic
`tests/fixtures/rooms/two-channel.json`, 30 Hz, seed 0, unrestricted available
publications per tick (0), normal delay 0 ms, and timestamped lead 1.5 s.
The default configuration is an export from a fresh offline Storage populated
with default model entities and a playable reference coupling. No running owner
instance was queried, activated or modified. The room positions are synthetic;
these are not measurements of the owner's area.

Regenerate each pair from the repository root with:

See [baseline regeneration commands](../README.md).

Replace FIXTURE with each committed WAV stem and ROUTE with normal/timestamped.
Copy only counters.json and meta.json to `FIXTURE/ROUTE/`; keep the CSVs local.
Meta records the actual executable revision and byte hashes. Later revisions
will intentionally change git_commit even if numerical counters remain equal.
See [trace schema](../../testing.md#replay-chain-and-trace-format) for all
counter definitions and the distinction between virtual wall time and measured
execution runtime. No physical sound, light or perceptual score is claimed.

The 120 BPM input has 19 truth clicks and 19 detected aggregate flags. With this
phase alignment, normal polling renders none of those flags; the timestamped
route renders every publication but coalesces some before sending. Those facts
are reference observations, not asserted physical event-loss rates or proposed fixes.
