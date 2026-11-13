# Beat-position delivery contract

Owner addendum: 2026-11-13. This extends BEAT-02 part B and replaces its part F;
it does not reopen part A or authorize a separate part push.

## Part B record

MusicalTimeline (`BeatFusion`) produces a frozen `BeatPosition` on every canonical
publication from its content-clock coordinate. Grid and tracker normalize their
beat coordinates before shared phase/count arithmetic. File, learned and rolling
grids use the same prior interface; the latter two arrive in parts C/D.

| Field | Meaning |
|---|---|
| `tempo` | BPM currently in force, or null in onset mode |
| `beat_phase` | Fraction of the current beat, 0–1 |
| `beat_index` | Beats counted from the first beat, zero based |
| `bar_phase` | Fraction of the current bar, 0–1 |
| `bar_index` | Bars counted from the first downbeat, zero based |
| `confidence` | Position confidence, capped at 0.5 until measured downbeats |
| `source` | Existing grid/tracker/onset label, never an ingress/output selector |
| `beats_per_bar` | Stored grid meter, otherwise 4 |
| `downbeat_measured` | False until the part F estimator is in use |

Explicit onset mode publishes the zero record. An acquiring tracker retains its
tracker label; no confidence or tempo is invented before its clock has a period.
A new identity resets counting. Analysis resets and seek epochs within the same
identity retain continuity. Source handovers align their counter offsets; a raw
handover discrepancy exceeding one beat is logged and counted in
`beat_index_jumps`. Looking up a predicted event does not advance frame counting.

Tempo/phase/confidence scalars remain deprecated for one release. Active grid
scalars mirror the record; cache/fetch/rejection diagnostics remain independent.
Effects keep beat-level behavior while `downbeat_measured` is false. Output drivers
consume Scenes and do not consume musical position. No new bar-based Effect is
introduced by this part.

The expert line reuses the current Analysis readout, for example:
`grid 128 BPM · beat 174 · bar 43.1`. A/B capture delegates accent CSV writing to
`ab-logger.py`, which adds `beat_index` and `bar_index` to every accent row. The
replay diagnostic event CSV retains its existing schema.

## Visual sketch used before implementation

```text
Now Playing / Analysis
  grid 128 BPM · beat 174 · bar 43.1
  [existing expert diagnostics and live controls]

CanonicalAnalysis → measured AudioFeatures → MusicalTimeline → Scheduler/Renderer
Grid database ───── prior / learned grids ────┘
  MusicalTimeline responsibilities:
  prior grid, live observations, correction, confidence, prediction
```

## Part F remains after E

The octave rule from the library survey must land before downbeat estimation.
Part F adds one estimator in the canonical grid analyser, using per-channel
attack flags, section carrying band, harmonic/spectral change and section starts.
It compares four phase candidates and carries phase across sections with
hysteresis. The live tracker receives the grid's downbeat and has no separate
estimator. Only that measured result can lift the confidence cap and set
`downbeat_measured`. Classical/opera keep no downbeat.

Part F's report must provide a plain-language method description and proposed
“1” clip start times in mm:ss.s at three disputed spots each for Mau P, UDKM and
Rockstar. The owner labels the clips; acceptance requires at least 8/9 agreement.
Lou Rawls is reported without an automatic acceptance threshold. The owner-only
LXC 115 survey supplies per-genre shares at downbeat confidence ≥0.7 for the report
and competitor table. No listening or survey evidence is fabricated here.

## Updated part B boundary (2026-11-13)

Back to automatic moves to COUPLE-01; no new reset actions belong to this commit.
Provider acquisition and owner corrections write normalized metadata only. The
resolver exposes its ranked result now; applying/seeding the tracker from priors
is part E. MusicalTimeline still uses measured grid/tracker time for BeatPosition.
