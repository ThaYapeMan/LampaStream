# Frozen analysis architecture

This is the current structural contract. Detailed runtime semantics live in
[audio-pipeline.md](audio-pipeline.md). Historical design prompts do not override it.

```text
Audio ingress → CanonicalAnalysisPipeline → SharedAnalysisFrame
    → AnalysisProcessor[]
        ├─ SpectrumProcessor → SpectrumEngine → V2 / CAVA Core / future
        ├─ BeatDetector → combined / multiband / Superflux onset algorithm
        ├─ LoudnessAnalyzer → KWeightedLoudnessAnalyzer → BS.1770 meter
        ├─ HpssAnalyzer → existing PcmHpss (optional)
        └─ ChromaAnalyzer → future algorithm (extension protocol only)
    → PublicationRecord → AudioFeatures → Effects → Scene → output driver
```

## Ownership

| Component | Owns |
|---|---|
| Source adapter | Transport, complete decoded frames, continuity detection and source events |
| PlayerManager | Source open/close, subprocesses and session lifecycle |
| CanonicalAnalysisPipeline | Canonicalizer, shared STFT, processor lifecycle, epoch/sample clocks, publication and worker |
| SharedAnalysisFrame | Read-only canonical PCM plus shared magnitudes and their hop positions |
| AnalysisProcessor | One feature family; zero or more exact-interval contributions |
| SpectrumProcessor | SpectrumEngine integration and block adaptation |
| SpectrumEngine | Spectrum algorithm, state, availability/effective identity |
| BeatDetector | Independent onset algorithm and its synchronized rebuild/reset |
| PublicationRecord | Atomic delivery identity, event interval, features and provenance |
| Effects | Generic AudioFeatures-to-Scene behavior |

Multiple processors can coexist. Dispatch is deterministic and sequential on the
pipeline worker, not concurrent calls to a single processor. `feed`, `flush`,
`reset` and `close` iterate the processor collection. Loudness has a production K-weighted momentary/short-term processor;
Chroma remains an extension protocol without a shipped algorithm.

## Shared analysis and Spectrum DSP

The shared StereoMagStft is 2048 samples, Hamming, with a 480-sample hop at 48 kHz.
V2 and Beat reuse its output. There is no second V2 FFT.

Embedded CAVA consumes canonical PCM directly. Its native path preserves upstream
4096 normal / 8192 bass FFTs, Hann windows, independent channels, band mapping,
compensation, autosensitivity, integral, gravity/fall and noise reduction. LampaStream
schedules 480 stereo frames per execution: **100 Hz source-audio cadence**.
Boundary conversion is float64 interleaved PCM ×32768. Conditioned channel bars
are averaged; no second V2 Spectrum conditioning follows CAVA.

## Registry and extension

`ENGINES`, `VALID_ENGINE_IDS` and `make_spectrum_engine()` in `spectrum_engine.py`
are the production engine source of truth. Validation checks IDs without requiring
native loading; activation checks availability. A new Spectrum implementation
requires its implementation, registry entry and tests, not new ingress/Effects
branches. The old whole-pipeline compatibility wrappers have been removed;
production and tests construct the shared canonical pipeline with its engine.

This is a static internal registry. There is no generic graph, node scheduler,
dynamic discovery or plugin framework. The architecture is frozen.

## Publication and latency

Publication **sequence orders delivery**. Sample intervals describe audio, and
may go backwards in delivery order when a slower processor produces its result.
Valid delayed contributions are never discarded merely to sort timestamps.

Within one dispatch, contributions group only by exact `(sample_start, sample_end)`.
Spectrum intervals are emitted first, then other first-seen intervals; equal keys
merge. Already published records are not mutated. No positional pairing or bounding
union is used. Fresh contributor IDs belong to that record only.

A bounded history of 1000 Spectrum records can provide bars from the exact same
interval, or from a completed interval ending no later than the contribution start.
`carried_spectrum_interval` identifies those historical bars; Spectrum is not added
to fresh contributor IDs. Missing history yields empty bars, not future bars or
lost Beat/Loudness/Chroma updates. No processor waits indefinitely for another.

`latest()` is the freshest audio-interval polling snapshot, not the last delivered
historical record. Within an epoch compare `(sample_end, sample_start)`; exact ties
prefer later delivery. A new epoch starts a fresh snapshot. Delayed records remain
in the delivery queue without rewinding live Effects. Consumers needing all records
use the bounded publication queue and check overflow. See
[audio-pipeline.md](audio-pipeline.md) for EOS, bounds and sequence semantics.

## Retirement and physical source safety

A stop timeout leaves ownership with SyncEngine. The old worker remains in
`_retiring`; unused replacement candidates are closed, and no second reader starts.
The worker closes its processors in `finally` once it exits.

SyncEngine.stop returns False if any owned analyser has not stopped. Manager teardown
checks that result and retirement state **before source close**. It retains the
session, reports a retriable error and marks `analysis_stopping`. A later deactivate
joins completed workers and releases the source; activation begins with this same
teardown gate. No forced source close is used to manufacture a successful join.

Ordinary candidate-start failure rebuilds the old configuration before committing
runtime replacement. Storage/session rollback and operational errors remain separate
from native availability checks. See [api.md](api.md).

## Ingress separation

AirPlay and LMS PCM use the common canonical factory. LMS SHM continuity is a
producer/source contract, not an analysis scheduler responsibility. Exact v1 is
required for production stereo PCM. See [SHM v1 ABI](../third_party/yeney-core/docs/shm-v1.md).

External CAVA/FIFO supplies derived bars and remains outside the processor/engine
registry. Its normalization and legacy PCM tap must not be copied into CAVA Core.

## Evidence boundary

These are implemented code contracts tested locally. Full target native execution,
SHM deployment, wheel installation, resource stress and visual comparison
**REQUIRE LXC VALIDATION**. This document does not claim those checks have passed.

## Content grid tempo sections

Grid analyser schema version 2 adds optional `Section.tempo`. The analyser stays
independent of players, LMS identities and lighting outputs. Tempo discontinuities
are detected with eight-beat slopes, sustained across sixteen slopes, avoiding
false changes caused by the tracker's sample-hop quantisation. Boundaries are
refined with local piecewise linear residuals. Rigid sections (interval spread
below 4%) use an inlier-fitted lattice with reassigned indices to remove tracker
insertions/deletions; expressive sections preserve tracker positions. One median
attack phase correction uses kick-bearing beats only.

Kick decisions compare nine-beat median on/off low-band attack energy against
section-relative contrast and level. Contrast is 40% of the section median
on/off ratio; the level is its on-beat p90 times max(0.02, 0.22 / max(1, ratio)).
A section requires peak-offset MAD at most 20 ms to claim kick support.
Four consecutive decisions confirm a state
change, backdated to the first confirming beat. Short silent gaps additionally
use a three-beat level median. The label tempo is the fitted tempo of the section
with the greatest kick-bearing duration (total duration breaks ties).

Old analyser-version cache entries are rejected by `TrackGrid.from_dict` and
re-analysed on next play. The next load uses the new cached full grid; provisional
head grids use the same fit/flag rules and never enter the full-file cache.

Strong evidence bypasses marginal hysteresis: at least 1.0× the kick-bearing
median turns a beat on, at most 0.25× turns it off. Kick-bearing runs anchor the
median; a 17-supported-beat median follows volume changes exceeding a factor 1.5.
Short breaks (up to 16 beats) identify isolated attack sections above 0.28× their
adjacent run anchor; long breaks require 8× their own background median. Each
isolated section has its own kick median. Other strong attacks must peak within
12 ms of the lattice, avoiding an unrelated bass note in the wider ±70 ms
marginal/absence window. After strong exceptions, marginal-only fragments shorter
than four beats merge into the neighbouring state. Strong single kicks and
single dropped kicks survive. These level sections are analyser-internal; the
optional published section tempo remains additive metadata.
