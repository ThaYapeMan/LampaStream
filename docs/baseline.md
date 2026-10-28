# Reproducible baseline

Baseline commit: **3998c440f464d0cf02743633fba98e8dd990743b** (master).
Recorded on **2026-10-24**, following the owner's *LampaStream bevindingen en
ontwikkelplan*, 24 October 2026. This is the comparison point for later phases,
not a claim that physical timing or perceptual quality has been measured.

## Build and validation environment

CI runs Python **3.11, 3.12 and 3.13** and Node **22.22.2**
(`.github/workflows/ci.yml:14`, `.github/workflows/ci.yml:51`). The local run below
uses Python **3.12.15** and Node **22.22.2**; it is not three Python-version runs.
Native prerequisites are `build-essential` and `libfftw3-dev`, exactly as listed
in `scripts/native-build-packages.txt:1`, plus **libflac-dev** for yeney-player.
Use the development environment from [development.md](development.md), including
the Python dev extra and locked frontend dependencies (`cd web && npm ci`).

Both `YENEY_CORE_REVISION` (`scripts/install-lampastream.sh:309`) and the
`third_party/yeney-core` gitlink are
**45779a4383929840a46a931fc1519b4778b64a72**. Check both when reproducing:

```sh
git rev-parse HEAD
git ls-tree HEAD third_party/yeney-core
grep YENEY_CORE_REVISION scripts/install-lampastream.sh
```

The standard test/build commands are:

```sh
pytest -v
ruff check .
cd web
npm test
npm run build
npm run test:e2e
```

For this recording, the full Python command was:

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -B -m pytest -v -ra -p no:cacheprovider
.venv/bin/python -m ruff check .
```

The extra flags avoid checkout caches, list skip reasons, and limit BLAS host
contention; they do not select a subset. Only licence/README metadata had changed
when Python ran; executable source was identical to the baseline commit
3998c440f464d0cf02743633fba98e8dd990743b. Frontend commands ran from `web/` in a
`git archive` copy of that exact commit under `/tmp/base01-snapshot`, sharing the
already installed locked `node_modules`. Playwright used `npm run test:e2e --
--workers=2`, Chromium and local HTTP/WebSocket fixtures. Generated assets and
screenshots stayed in the temporary copy. Nothing contacted the reference setup.

| Check | Actual result, 2026-10-24 |
|---|---|
| Full pytest | 1,794 passed, 93 skipped, 5 warnings (97.71 s) |
| Ruff | All checks passed |
| Frontend unit | 26 files, 437 tests passed |
| Frontend production build | Passed; 1,978 modules; bundle-size warning above 500 kB |
| Playwright | 69 passed (32.4 s) |

The 93 skips cover unavailable soundfile, native CAVA/CavaCore execution and the installer
case reserved for unsupported review hosts. Five warnings are Starlette/httpx
and FastAPI startup/shutdown deprecations. Exact skip reasons remain in the full
transcript; a skipped native test is
not evidence of native execution. The full run transcripts are local artifacts
in `/tmp/base01/{pytest,ruff,frontend,frontend-build,playwright}.txt`; those paths
are evidence from this recording, not durable dependencies or committed fixtures.
[testing.md](testing.md) explains native evidence boundaries and reproducing checks.

## Reference setup

These are owner-supplied setup facts, not observations from this task:

| Component | Location / identity |
|---|---|
| LampaStream | LXC 112, 192.168.178.24 |
| LMS | LXC 111, 192.168.178.23 |
| YeneY | LXC 113, 192.168.178.31 |
| Hue Bridge | 192.168.178.19 |
| Lamps | Include Hue Iris |
| Players | LampaStream LMS virtual player; AirPlay receiver; Sonos “Study” and “Sonos Port” via YeneY; Squeezebox Radio “Radio Red”; piCorePlayer |

The virtual LMS player supplies analysis PCM. Sonos through YeneY is a followed
LMS player, not a native Sonos ingress. No deployment or live probing was done.

## Information conditions

| Condition from the plan | Available path at baseline commit 3998c440f464d0cf02743633fba98e8dd990743b |
|---|---|
| Live without lookahead | `pcm_source.py:364` (`SqueezeliteShmStereoSource`) and `pcm_source.py:1166` (`AirPlayPipeStereoSource`), through `CanonicalAnalysisPipeline` (`sync_engine.py:983`) and the normal `latest()`/delay route (`sync_engine.py:3210`). A delay buffer does not itself provide future audio. |
| Live with measured lookahead | AirPlay early tap, approximately **1.5–2 s** in the reference condition: `airplay_early.py:107` (`EarlyAirPlaySource`), carrying receipt/play clocks. LMS head start, configured **500 ms** by default (`models.py:393`): `lms_timing.py:28`, `lms_timing.py:300`, optional SHM player clock (`player_clock.py:13`). Both reach `SceneSchedule` (`airplay_early.py:333`) via `sync_engine.py:3169`. Lead is diagnosed at runtime; these reference values are not newly measured guarantees. |
| Whole track accessible | **None** in the live product. `scripts/run_acceptance.py` can decode a local file for offline analysis; it does not implement whole-track lookahead or precomputed live rendering. |

Unqualified source filenames above are under `src/lampastream/`; references are
line numbers at the full baseline commit stated above. See [code-map.md](code-map.md)
for contracts and [measurement-protocol.md](measurement-protocol.md) for evidence rules.

## Not measured yet

- Physical audio-to-light latency.
- p50/p95/p99 output timing.
- Event loss/duplication rate on the normal output route.
- Perceptual quality.

## BENCH-01 full-chain synthetic reference

The phase-zero comparison baseline remains
**3998c440f464d0cf02743633fba98e8dd990743b**. BENCH-01 adds reproducible offline
reference numbers using executable revision
**b36f5d97d3af2cf846208c2097e3f3ff3d1b44a3**: ten generated fixtures, both output
routes, default-model exported configuration, synthetic two-channel room, 30 Hz,
seed 0. [Reference counters and metadata](baseline/traces/README.md) include all
20 runs; CSVs remain local. [Replay documentation](testing.md#replay-chain-and-trace-format)
defines timestamps, event attribution and reproduction. These virtual traces do
not fill in the physical or perceptual “Not measured yet” items above.

## Phase 1 regression numbers at 135ab38563baba1f4d5a7f2dcd67e349e5f2f88d

These REG-01 pins describe the unchanged production/harness behavior at the full
commit in the heading. Seed 0; default exported configuration (combined), plus
an explicit multiband-only override for band measurements. All numeric pins live
in `tests/fixtures/onset-regression-numbers.json`; neither tests nor CI regenerate
expected values. The contracts remain strict expected failures owned by TIME-01
or EVENT-01. These are software observations, not physical timing measurements.

### Isolated Dixon picker

| Raw peak frames (strength) | Current report frames | Returned strength | After 500 silence frames |
|---|---|---|---|
| 50 (10) | 53 | 0 | 503 (0.1), 553 (0) |
| 50 (10), 70 (10) | 53, 73 | 0, 0 | 503 (0.1), 553 (0), 573 (0) |
| 50 (10), 52 (3) | 53 only | 0 | 503 (0.1), 553 (0) |

Warmup input is 50 frames of raw ODF 0.1; the tail is zero except specified
peaks. Normalization occurs inside the picker. Silence adds a transition onset
when low flux resumes. A separate 50-frame ODF=0.2 priming gives EMA
**0.198969244958536**, decaying to **2.630514327338083e-24** after 500 zero frames.
The three-frame candidate/report gap is separate from FFT window reference.

### Truth, candidate and availability

Route is **both normal and timestamped**, 30 Hz, unrestricted delivery. Each
offset cell gives **hops (samples)**, observed minus truth; max is maximum
absolute magnitude. A/C misses and false positives use separate ±2-hop windows.
One hop is 480 samples. Alignment misses are not necessarily missing detections.

| Fixture | Method / active bands | Events | Availability median / max | Candidate median / max | A misses/FP | C misses/FP | Availability−candidate hops |
|---|---|---:|---|---|---|---|---|
| clicks-120 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | 19 | 5 (2400) / 5 (2400) | -3 (-1440) / 4 (1920) | 19/19 | 19/19 | 8 |
| clicks-128 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | 21 | 4.625 (2220) / 5.125 (2460) | -3.375 (-1620) / 4 (1920) | 21/21 | 21/21 | 8 |
| clicks-174 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | 28 | 4.844792 (2325.5) / 5.345833 (2566) | -3.155208 (-1514.5) / 4 (1920) | 28/28 | 28/28 | 8 |
| impulse | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | 1 | 4 (1920) / 4 (1920) | -4 (-1920) / 4 (1920) | 1/1 | 1/1 | 8 |
| panning | combined/all, multiband/treble | 19 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 5 (2400) | 19/19 | 19/19 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |
| panning | multiband/all | 20 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 4 (1920) | 19/20 | 19/20 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |
| panning | multiband/bass, multiband/mid | 19 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 4 (1920) | 19/19 | 19/19 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |
| anti-phase | combined/all, multiband/mid, multiband/treble | 19 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 5 (2400) | 19/19 | 19/19 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |
| anti-phase | multiband/all | 20 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 4 (1920) | 19/20 | 19/20 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |
| anti-phase | multiband/bass | 19 | 4.625 (2220) / 5.208333 (2500) | -3 (-1440) / 4 (1920) | 19/19 | 19/19 | {7.333333, 7.458333, 7.5, 7.625, 7.75, 7.875, 7.916667, 8.041667, 8.166667, 8.208333} |

Default combined bass/mid/treble are unavailable: zero events, every truth
event an alignment miss, zero false positives, no offset or lookahead reading.
The multiband panning/anti-phase union has 20 events versus 19 truth clicks.
At 48 kHz, candidate-window-start to availability is 3840 samples (8 hops);
at 24 kHz the multiple gap values expose chunk-dependent availability.
TIME-01 must choose the authoritative event reference and numeric lookahead.

### Panning halves (both routes, 30 Hz)

Left means truth <5 s (9 clicks), right means >=5 s (10 clicks). Medians below
are nearest-event observations, not a claim that panning amplitudes are equal.

| Method/band | Availability offset L/R hops | Candidate offset L/R hops | Candidate strength L/R | Reported strength L/R |
|---|---|---|---|---|
| combined/all | 4.75 / 4.625 | -3 / -3 | 271.908007 / 277.083246 | 16.725472 / 16.418587 |
| multiband/all | 4.75 / 4.625 | -3 / -3 | 250.780489 / 255.55328 | 16.725472 / 16.418587 |
| multiband/bass | 4.75 / 4.625 | -3 / -3 | 2.703904 / 2.755079 | 0 / 0 |
| multiband/mid | 4.75 / 4.625 | -3 / -3 | 18.423615 / 18.774886 | 0 / 0 |
| multiband/treble | 4.75 / 4.625 | -3 / -3 | 250.780489 / 255.55328 | 16.725472 / 16.418587 |

### Strength and rank (both routes, 30 Hz)

Click strengths are raw candidate ODF, first click then the identical remaining
18 clicks. Every reported main-click strength is 0; the fraction below 10% of
maximum candidate strength is **1.0** in each enabled band.

| Method/band | Candidate first / remaining | Reported | Below-tenth fraction |
|---|---|---|---|
| combined/all | 175.980262 / 874.513342 | 0 | 1.0 |
| multiband/all | 0.514213 / 2.478872 | 0 | 1.0 |
| multiband/bass | 0.514213 / 2.478872 | 0 | 1.0 |
| multiband/mid | 3.435347 / 16.765215 | 0 | 1.0 |
| multiband/treble | 172.030703 / 855.269254 | 0 | 1.0 |

For tone levels −30/−20/−10/−3 dBFS, startup has no detected event. Its
presence bit is false, with zero only as a rank-calculation placeholder. The
table lists the remaining −20/−10/−3 transients. Spearman includes all four level
positions with tied average ranks; constant strengths have undefined rho. The
already-correct rho=1 is preserved; its xfailed contract additionally requires
candidate attribution rather than falsely claiming monotonicity is broken.

| Method/band | Candidate at −20/−10/−3 | Reported at −20/−10/−3 | Four-level rho |
|---|---|---|---|
| combined/all | 12.494626 / 39.523286 / 68.250828 | 21.435945 / 67.78344 / 130.536063 | 1.0 |
| multiband/all | 7.714525 / 24.393061 / 41.288589 | 20.713276 / 65.496758 / 125.032005 | 1.0 |
| multiband/bass | 0.42369 / 1.339629 / 2.225437 | 0 / 0 / 0 | undefined |
| multiband/mid | 7.714525 / 24.393061 / 41.288589 | 20.713276 / 65.496758 / 125.032005 | 1.0 |
| multiband/treble | 4.356412 / 13.790596 / 24.736803 | 0.722669 / 2.286682 / 5.504058 | 1.0 |

### Event survival

Each tuple is **received/accepted/rendered/merged/expired/lost**. N=normal,
T=timestamped; free=unrestricted publications per tick; cap1=one per tick.
Rows group bands only when every tuple is identical. No event tolerance hides
loss; all integer tuples are exact deterministic pins. Inactive combined bands
are `(0,0,0,0,0,0)` throughout.

| Fixture | Method/bands | N30 free | N60 free | N30 cap1 | N60 cap1 | T30 free | T60 free | T30 cap1 | T60 cap1 |
|---|---|---|---|---|---|---|---|---|---|
| clicks-120 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | (19,0,0,0,0,19) | (19,18,18,0,0,1) | (19,19,19,0,0,0) | (19,19,19,0,0,0) | (19,19,19,1,0,1) | (19,19,19,1,0,1) | (19,19,19,1,0,1) | (19,19,19,1,0,1) |
| clicks-128 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | (21,5,5,0,0,16) | (21,12,12,0,0,9) | (21,21,21,0,0,0) | (21,21,21,0,0,0) | (21,21,21,14,0,14) | (21,21,21,9,0,9) | (21,21,21,1,0,1) | (21,21,21,2,0,2) |
| clicks-174 | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | (28,8,8,0,0,20) | (28,16,16,0,0,12) | (28,28,28,0,0,0) | (28,28,28,0,0,0) | (28,28,28,20,0,20) | (28,28,28,12,0,12) | (28,28,28,1,0,1) | (28,28,28,3,0,3) |
| impulse | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | (1,0,0,0,0,1) | (1,0,0,0,0,1) | (1,1,1,0,0,0) | (1,1,1,0,0,0) | (1,1,1,1,0,1) | (1,1,1,1,0,1) | (1,1,1,0,0,0) | (1,1,1,0,0,0) |
| panning | combined/all, multiband/treble | (19,1,1,0,0,18) | (19,14,14,0,0,5) | (19,19,19,0,0,0) | (19,19,19,0,0,0) | (19,19,19,2,0,2) | (19,19,19,1,0,1) | (19,19,19,1,0,1) | (19,19,19,0,0,0) |
| panning | multiband/all | (20,1,1,0,0,19) | (20,14,14,0,0,6) | (20,20,20,0,0,0) | (20,20,20,0,0,0) | (20,20,20,3,0,3) | (20,20,20,2,0,2) | (20,20,20,2,0,2) | (20,20,20,1,0,1) |
| panning | multiband/bass, multiband/mid | (19,0,0,0,0,19) | (19,13,13,0,0,6) | (19,19,19,0,0,0) | (19,19,19,0,0,0) | (19,19,19,2,0,2) | (19,19,19,2,0,2) | (19,19,19,1,0,1) | (19,19,19,1,0,1) |
| anti-phase | combined/all, multiband/mid, multiband/treble | (19,1,1,0,0,18) | (19,14,14,0,0,5) | (19,19,19,0,0,0) | (19,19,19,0,0,0) | (19,19,19,2,0,2) | (19,19,19,1,0,1) | (19,19,19,1,0,1) | (19,19,19,0,0,0) |
| anti-phase | multiband/all | (20,1,1,0,0,19) | (20,14,14,0,0,6) | (20,20,20,0,0,0) | (20,20,20,0,0,0) | (20,20,20,3,0,3) | (20,20,20,2,0,2) | (20,20,20,2,0,2) | (20,20,20,1,0,1) |
| anti-phase | multiband/bass | (19,0,0,0,0,19) | (19,13,13,0,0,6) | (19,19,19,0,0,0) | (19,19,19,0,0,0) | (19,19,19,2,0,2) | (19,19,19,2,0,2) | (19,19,19,1,0,1) | (19,19,19,1,0,1) |
| tone-steps | combined/all, multiband/all, multiband/bass, multiband/mid, multiband/treble | (3,0,0,0,0,3) | (3,0,0,0,0,3) | (3,3,3,0,0,0) | (3,3,3,0,0,0) | (3,3,3,3,0,3) | (3,3,3,3,0,3) | (3,3,3,0,0,0) | (3,3,3,1,0,1) |

Publication tuples below are **consumed-once/skipped/repeated** identities,
not the number of render reads. Both methods and all fixtures in a row share
counts. Timestamped counts are the same at both rates and caps.

| Fixtures | N30 free | N60 free | N cap1 (30/60) | Timestamped (30/60, free/cap1) |
|---|---|---|---|---|
| clicks-120/128/174, panning, anti-phase | (298,697,1) | (597,398,1) | (995,0,1) | (996,0,0) |
| impulse | (178,417,1) | (357,238,1) | (595,0,1) | (596,0,0) |
| tone-steps | (238,557,1) | (477,318,1) | (795,0,1) | (796,0,0) |

For every normal-route row/band, the number of never-consumed onset-flag
publications and sole-carrier losses both equal its last (`lost`) tuple value.
Both counts are zero on the timestamped route, whose losses instead come from
scheduler coalescing. In particular, **19** flags in clicks-120 normal/30/free
sit on publications never present in energy.csv consumed_sequences. This matches
BENCH-01 exactly; no baseline discrepancy was observed.

## Phase 2 numbers at 757de73

EVENT-01 reference code, default combined analyser, synthetic two-channel room,
seed 0, 30 Hz, unrestricted publications. The phase-one table above remains an
unchanged historical record. Phase-two counters use unique event identities and
trigger dispositions; accepted/rendered flag-read counts are retired. Full counters,
metadata and event rows are in [traces](baseline/traces/README.md); the original
set is retained in [traces-phase0](baseline/traces-phase0/README.md).

| Fixture / route | Phase 1 received / lost | Phase 2 received / triggered / merged / expired / lost |
|---|---:|---:|
| clicks-120 / normal | 19 / 19 | 19 / 19 / 0 / 0 / 0 |
| clicks-120 / timestamped | 19 / 1 | 19 / 19 / 0 / 0 / 0 |
| clicks-174 / normal | 28 / 20 | 28 / 28 / 0 / 0 / 0 |
| clicks-174 / timestamped | 28 / 20 | 28 / 28 / 0 / 0 / 0 |
| tone-steps / normal | 3 / 3 | 3 / 3 / 0 / 0 / 0 |
| tone-steps / timestamped | 3 / 3 | 3 / 3 / 0 / 0 / 0 |

| Detector quantity | Phase 1 | Phase 2 |
|---|---|---|
| clicks-120 candidate median / maximum absolute error | −1440 / 1920 samples | 0 / 0 samples |
| clicks-174 candidate median / maximum absolute error | −1514.5 / 1920 samples | 140.5 / 381 samples |
| Confirmation − candidate | 8 hops at 48 kHz; chunk-dependent after resampling | 1 hop, including resampled fixtures |
| Candidate-attributed tone strength, combined | No | Yes; Spearman rho = 1 |
| Silence reference after 500 zero frames | EMA decays to 2.630514327338083e-24 | EMA frozen at 0.19885471662059553 |
| Low-flux resumption transition event | Yes | No |
| REG-01 strict contract xfails | 133 | 0 (236 regression tests pass) |

These are detector coordinates and software event survival, not physical light
measurements. The tighter phase acceptance remains unmet: clicks-174 normal/30
first sends range approximately +31 to +66 ms, and timestamped sends approximately
−21 to +18 ms relative to truth plus playback lead. The event queue removes loss,
but the shared complete STFT window still adds acquisition delay and timestamped
hop/render quantization remains. A candidate/confirmation coordinate gap of one hop
must not be reported as one hop of end-to-end processing latency.

The clean pre-change full suite at e03f1a8 passed 1,921 tests, skipped 93 and xfailed
133 in 190.95 s. The first all-green phase-two full run passed 2,062 tests, skipped
93 and xfailed zero in 176.45 s; final verification adds nine focused cases and is
reported with the task transcript. No frontend rebuild, deployment or physical
source/output access was performed.

Final full verification: **2,071 passed, 93 skipped, zero xfails, five warnings in
210.59 s**, versus the clean pre-change 190.95 s. The measured final run is 19.64 s
slower; the requested wall-time acceptance is not demonstrated. Ruff passes.

## LAT-01 starting point at 542b9ed

Measured with the unchanged phase-two DSP/output loop, default configuration,
30 Hz, unrestricted delivery. Times are software milliseconds; timestamped
first-send values include the replay 1500 ms playback lead.

| Fixture | Route | Truth → send median / p95 / max (ms) |
|---|---|---:|
| clicks-120 | normal | 33.333 / 33.333 / 33.333 |
| clicks-120 | timestamped | 1500.000 / 1500.000 / 1500.000 |
| clicks-128 | normal | 47.917 / 62.500 / 62.500 |
| clicks-128 | timestamped | 1497.917 / 1520.833 / 1525.000 |
| clicks-174 | normal | 48.844 / 62.807 / 65.521 |
| clicks-174 | timestamped | 1498.281 / 1516.040 / 1518.396 |
| impulse | normal | 33.333 / 33.333 / 33.333 |
| impulse | timestamped | 1500.000 / 1500.000 / 1500.000 |
| panning | normal | 33.333 / 33.333 / 33.333 |
| panning | timestamped | 1500.000 / 1500.000 / 1500.000 |

LAT-01 short-window step (lookahead 1, cadence unchanged): clicks-120 and impulse
window acquisition falls 20→10 ms; clicks-128/174 typically lose 20 ms. The
remaining render wait can absorb that gain (clicks-120 still sends at 33.333 ms).
Raw pink-noise event counts 79→82 motivated log-filtered short flux (80 events);
sweep changes 309→303. No detector threshold was increased.

### LAT-01 lookahead decision

Combined log-filtered short front end; normal 30 Hz. Match within two hops,
count unmatched events and extra events assigned to an already matched truth.
Tone-step startup remains a warmup miss; noise/sweep have empty sparse truth.
| Fixture | Lookahead | Events | Misses | False positives | Double hits |
|---|---:|---:|---:|---:|---:|
| anti-phase | 0 | 19 | 0 | 0 | 0 |
| anti-phase | 1 | 19 | 0 | 0 | 0 |
| clicks-120 | 0 | 19 | 0 | 0 | 0 |
| clicks-120 | 1 | 19 | 0 | 0 | 0 |
| clicks-128 | 0 | 21 | 0 | 0 | 0 |
| clicks-128 | 1 | 21 | 0 | 0 | 0 |
| clicks-174 | 0 | 28 | 0 | 0 | 0 |
| clicks-174 | 1 | 28 | 0 | 0 | 0 |
| impulse | 0 | 1 | 0 | 0 | 0 |
| impulse | 1 | 1 | 0 | 0 | 0 |
| panning | 0 | 19 | 0 | 0 | 0 |
| panning | 1 | 19 | 0 | 0 | 0 |
| pink-noise | 0 | 82 | 0 | 82 | 0 |
| pink-noise | 1 | 80 | 0 | 80 | 0 |
| silence | 0 | 0 | 0 | 0 | 0 |
| silence | 1 | 0 | 0 | 0 | 0 |
| sweep | 0 | 308 | 0 | 308 | 0 |
| sweep | 1 | 303 | 0 | 303 | 0 |
| tone-steps | 0 | 3 | 1 | 0 | 0 |
| tone-steps | 1 | 3 | 1 | 0 | 0 |

## Phase 3 (LAT-01) numbers at c5e6a7e

Default combined analyser, synthetic room, seed 0, unrestricted delivery, 30 Hz.
[Raw per-event ledgers and counters](baseline/lat01/README.md) preserve both runs.
The phase-two section and its unmet acceptance remain historical evidence.

| Fixture | Route | Before median / p95 / max (ms) | After median / p95 / max (ms) |
|---|---|---:|---:|
| clicks-120 | normal | 33.333 / 33.333 / 33.333 | 20.000 / 20.001 / 20.001 |
| clicks-120 | timestamped | 20.000 / 20.000 / 20.000 | 5.000 / 5.000 / 5.000 |
| clicks-128 | normal | 47.917 / 62.500 / 62.500 | 17.917 / 30.417 / 36.667 |
| clicks-128 | timestamped | 17.917 / 40.833 / 45.000 | 0.000 / 5.000 / 5.000 |
| clicks-174 | normal | 48.844 / 62.807 / 65.521 | 19.053 / 31.436 / 34.938 |
| clicks-174 | timestamped | 18.281 / 36.040 / 38.396 | 0.344 / 4.529 / 5.000 |
| impulse | normal | 33.333 / 33.333 / 33.333 | 20.000 / 20.000 / 20.000 |
| impulse | timestamped | 20.000 / 20.000 / 20.000 | 5.000 / 5.000 / 5.000 |
| panning | normal | 33.333 / 33.333 / 33.333 | 20.000 / 20.001 / 20.001 |
| panning | timestamped | 20.000 / 20.000 / 20.000 | -5.000 / -5.000 / -5.000 |

Normal values: truth → first lifted send. Timestamped values: signed error
from truth + 1500 ms playback lead − 20 ms light advance. Both at 30 Hz.
The latency tests also cover 60 Hz. Timestamped absolute truth error is ≤5 ms.

| clicks-120 normal 30 Hz term | Before median / p95 / max (ms) | After median / p95 / max (ms) |
|---|---:|---:|
| window_acquisition_ms | 20.000 / 20.000 / 20.000 | 10.000 / 10.000 / 10.000 |
| hop_ms | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 |
| lookahead_ms | 10.000 / 10.000 / 10.000 | 10.000 / 10.000 / 10.000 |
| tick_wait_ms | 3.333 / 3.333 / 3.333 | 0.000 / 0.000 / 0.000 |
| schedule_wait_ms | 0.000 / 0.000 / 0.000 | 0.000 / 0.001 / 0.001 |

The 512-sample right-aligned front end reduces acquisition, while event-triggered
sends remove cadence wait. One-hop lookahead remains the default after the table
above showed extra noise/sweep events at zero lookahead. Timestamped event
boundaries use a half-hop playback estimate and exact heap deadlines; positive
onset_lead_s still advances light before audio. No physical transport delay is
measured here. Tests assert median ≤30 ms and max ≤40 ms on the normal route,
and ±5 ms against truth plus playback lead minus light advance on the timestamped
route, for all three BPM fixtures and impulse at both 30 and 60 Hz.

Phase-two idle-colour comparisons pass on silence, sweep and pink noise, on both
routes, with onset detection explicitly disabled on both revisions. Complete
send times, floating RGB traces and effective output bytes match their immutable
phase-two hashes. No intensity or threshold default was increased.

The normal delay-shrink burst test remains unchanged and passes. The extra-send
spacing tests include a render that takes longer than the minimum send interval,
so one-extra-per-drain is enforced explicitly rather than assumed from CPU speed.

Final verification at c5e6a7e (Python 3.12.15, BLAS threads=1): **2,114 passed,
93 skipped, 5 warnings in 142.48 s; measured wall 142.726 s** on CPU 5. Four-worker
`-n auto` on CPUs 5/7/13/15: **2,114 passed, 93 skipped, 20 warnings in 60.76 s;
measured wall 60.996 s**. Both runs start with cold session-local replay caches.
The unchanged native/host-dependent skips remain explicit in the complete
[one-core transcript](baseline/lat01/pytest-one-core.txt) and
[four-core transcript](baseline/lat01/pytest-four-core.txt). Both ≤190 s one-core
and ≤90 s four-core targets pass; `ruff check .` passes. The additional four-core
warnings are worker-local repetitions of the same existing warnings.

Final [headroom](baseline/lat01/headroom.md), [lookahead comparison](baseline/lat01/lookahead.md)
and [phase-two colour hash checks](baseline/lat01/colour-check.md) are retained
alongside the raw event ledgers. No frontend build, deployment or physical
source/output access was performed.


## Phase 4 (ACCENT-01)

Reference: `docs/baseline/traces-phase4/` for clicks-120, clicks-174, tone-steps
and pink-noise, both routes, visible default accents. Earlier phase sets remain
unchanged. The default-spectrum clicks-120 normal trace accents all 19 events,
loses zero, reaches 82.81 output codes of additional lift and clips zero channels.

All-effects clicks-120 acceptance below uses the default parameters with both
Effects set to the indicated factory ID, both routes, and the declared-depth
room. Max lift is pre-output-boundary additional lift; duration is the minimum
observed display span above eight codes within each event's 500 ms isolated
window, including the final displayed frame. Consequently durations are bounded
by the next click rather than representing a complete exponential tail. The
requirements are ≥80 ms on the slow room and ≥33.3 ms on the fast room.

| Effect | Max lift (8-bit LSB) | Min visible ms (25 Hz) | Max lift (16-bit LSB) | Min visible ms (60 Hz) | Max clipped components/light |
|---|---:|---:|---:|---:|---:|
| band_colours | 61.33 | 486.7 | 13659.00 | 475.0 | 0 |
| band_colours_spatial | 136.84 | 486.7 | 34249.12 | 475.0 | 0 |
| fireworks | 25.27 | 466.7 | 5473.88 | 475.0 | 0 |
| flashes | 45.08 | 486.7 | 11586.59 | 475.0 | 0 |
| gradient | 101.42 | 486.7 | 23991.58 | 475.0 | 0 |
| mono_pulse | 112.12 | 486.7 | 27113.07 | 475.0 | 0 |
| pulses | 43.12 | 486.7 | 11084.26 | 475.0 | 0 |
| solid | 112.12 | 486.7 | 27113.07 | 475.0 | 0 |
| spectrum_rgb | 90.29 | 486.7 | 20782.79 | 475.0 | 0 |
| spectrum_rgb_spatial | 138.48 | 486.7 | 34725.75 | 475.0 | 0 |
| splotches | 125.12 | 486.7 | 32154.68 | 475.0 | 0 |
| swirl | 103.61 | 486.7 | 24625.63 | 475.0 | 0 |
| wave | 125.06 | 486.7 | 32141.64 | 475.0 | 0 |

Every one of the 19 received events passes in all 52 cases, with zero lost events.
Hue stays within one degree and maximum clipped components are zero. Flashes
reserves 15% internal peak headroom when enabled; off retains LAT-01 intensity.
All ten fixture × two route accent-off runs match complete LAT-01 sends/features/
energy/events bytes, anchored at 6986d9a; the one-time audit also matches every
original render column. Hash expectations are stored in
`tests/fixtures/accent-off-lat01.json` and continuously tested.

### Audible preview: Send-back 2 and PREVIEW-01

Controlled clicks-120 replay, 19 events per route; timestamped ingress lead 1.5 s.
Positive residual means preview activation after its audible reference. These are
software clocks, excluding physical output and uncontrolled network/browser load.

| Probe | Events | Residual / delivery lead (ms) |
|---|---:|---:|
| Send-back 2 periodic normal, 0 / 200 ms buffer | 19 each | activation +46.999…+47.000 |
| Send-back 2 periodic timestamped, 20 / 100 ms lamp advance | 19 each | activation +17.000 |
| PREVIEW-01 normal push, 0 / 200 ms buffer | 19 each | publication minus carrying send 0.000 |
| PREVIEW-01 timestamped push, 20 / 100 ms lamp advance | 19 each | publication minus playback −1466.667 |
| PREVIEW-01 Vitest, known offset, 16 ms animation interval | 1 | scheduled activation minus audible +8.000 |
| PREVIEW-01 Playwright, future socket event, controlled clock | 1 | scheduled activation minus audible +6.000…+7.000 |

The pushed timestamped event is available well before playback; its browser
activation is deliberately deferred to playback. The two browser probes measure
residual activation error after clock conversion, rather than claiming 1466 ms
of latency. Repeated Playwright runs measured 6 and 7 ms as animation phase varied.
All scheduled activations are at or after the target and within one
animation frame. The normal-route push removes the 20 Hz wait but still incurs
transport and the next browser animation frame. Unknown offset explicitly falls
back to immediate drawing and is labelled unsynchronised. RTT/offset are visible
in Light timing. Existing periodic probes remain as cadence/compatibility checks.

Active-accent sends.csv is byte-identical to 8f5385b for normal (0 and 200 ms delay)
and timestamped output; all 20 LAT-01 accent-off fixture/route hash pins remain
unchanged. No physical device was contacted.

## Phase 5 (BEAT-01)

Core implementation: `3262918`; local synthetic PCM only, no deployed hardware.
All loops are 12 s; room is 25 Hz / 8-bit, render cadence 30 Hz. Before means
all-bin diagnostic onsets/s; the old stream had no separate texture count.
After separates visible beat and texture events. Lock coordinates below are
source publication coordinates; acquisition/availability is separately retained
in traces. Kick latency excludes texture events and predictions.

| Fixture | Before onsets/s | Beat/s | Texture/s | Kick recall | False bass triggers | BPM (alternate) | Lock s | On-beat kicks | Duty ch0/ch1 | Median kick→send ms |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|---:|
| breakbeat | 11.167 | 2.417 | 1.667 | 17/17 | 0 | 173.91 (86.96) | 3.92 | 1.00 | 58.9%/58.9% | 23.792 |
| breakdown | 12.333 | 1.917 | 2.667 | 15/15 | 0 | 119.76 (59.98) | 2.98 | 1.00 | 44.6%/44.6% | 30.000 |
| deep-house | 2.167 | 2.000 | 0.000 | 24/24 | 0 | 121.98 (60.86) | 3.43 | 1.00 | 59.2%/59.2% | 27.302 |
| disco | 11.250 | 1.667 | 3.417 | 20/20 | 0 | 100.00 (200.00) | 3.47 | 1.00 | 49.2%/49.2% | 20.000 |
| house | 11.667 | 1.917 | 2.167 | 23/23 | 0 | 120.00 (60.00) | 2.98 | 1.00 | 60.4%/60.4% | 30.000 |
| pad-texture | 19.333 | 0.000 | 0.000 | — | 0 | — | — | — | 0.0%/0.0% | — |
| techno | 10.250 | 2.083 | 1.833 | 25/25 | 0 | 127.79 (63.88) | 3.29 | 1.00 | 62.9%/62.9% | 26.917 |
| tempo-change | 11.333 | 2.000 | 2.917 | 24/24 | 0 | 128.09 (64.21) | 2.98 | 1.00 | 60.7%/60.7% | 30.000 |

All cases have zero lost events. Pink noise: **2 triggers / 5 s = 0.4/s**,
sweep: **6 / 20 s = 0.3/s**; pad: zero beat and texture events. Beat periods
and kick counts are independent sidecar truth, not values regenerated by tests.
Tempo change relocks at 9.77 s, 3.77 s after the change. Missing breakbeat-grid
predictions have at most 389 samples (8.104 ms) error. Breakdown contains eight
predictions and zero false bass triggers in its missing-kick interval.

Duty is above floor +0.10 in **linear light**, relative to each carrying render’s
base colour. It integrates the quantised setpoint held between actual sends;
it is not a photometric or perceptual measurement.
Actual output tests pass both the 25 Hz/8-bit and 60 Hz/16-bit rooms, with
between-kick output ≤ floor +0.10. Alternate gives 12 flashes out of 23 beats;
Divisor 4 gives 6. Texture-only lift is below 25% of kick lift. Timestamped Pulse
has matching half-peak samples 40 ms before and after the first beat.

Additional house traces cover timestamped output and the fast room. Timestamped
candidate boundaries retain the configured 20 ms advance before the event’s
audible play time; their approximately 1.48 s source-to-send difference includes
the deliberate 1.5 s ingress head start and must not be read as live-route latency.

### Phase-five CPU and reproducibility

One-core replay benchmark (affinity CPU 5; BLAS/OMP threads 1):

Affinity: [5]

| Fixture | Route | Hz | DSP CPU ms/hop | Loop p95 / max ms | Core % | Margin | Virtual backlog | Pub / event drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pink-noise | normal | 30 | 0.724 | 0.016 / 1.517 | 8.8 | 11.38× | 0 | 0 / 0 |
| pink-noise | normal | 50 | 0.708 | 0.284 / 0.579 | 9.3 | 10.76× | 0 | 0 / 0 |
| pink-noise | normal | 60 | 0.717 | 0.209 / 25.511 | 10.1 | 9.89× | 0 | 0 / 0 |
| pink-noise | timestamped | 30 | 0.707 | 1.115 / 1.346 | 10.0 | 9.95× | 0 | 0 / 0 |
| pink-noise | timestamped | 50 | 0.708 | 0.864 / 1.123 | 10.4 | 9.62× | 0 | 0 / 0 |
| pink-noise | timestamped | 60 | 0.706 | 0.526 / 1.530 | 10.6 | 9.47× | 0 | 0 / 0 |
| clicks-174 | normal | 30 | 0.771 | 0.013 / 36.546 | 9.5 | 10.52× | 0 | 52 / 0 |
| clicks-174 | normal | 50 | 0.783 | 0.050 / 0.981 | 9.9 | 10.11× | 0 | 52 / 0 |
| clicks-174 | normal | 60 | 0.787 | 0.212 / 42.687 | 10.7 | 9.35× | 0 | 52 / 0 |
| clicks-174 | timestamped | 30 | 0.774 | 1.107 / 1.618 | 10.8 | 9.26× | 0 | 0 / 0 |
| clicks-174 | timestamped | 50 | 0.774 | 0.677 / 1.631 | 11.2 | 8.95× | 0 | 0 / 0 |
| clicks-174 | timestamped | 60 | 0.779 | 0.672 / 45.234 | 11.9 | 8.42× | 0 | 0 / 0 |

Clock update: 0.269 µs; trigger/hypothesis update: 19.395 µs.

The eight musical/control fixture DSP measurements are also recorded individually
in `traces-phase5/measurements.json`. Two independent house runs have identical
SHA-256 hashes for all eight trace files; see `determinism-sha256.json`.
Host-measured CPU time is deliberately outside the deterministic trace hashes.

Private excerpts: `/home/codex/src/private-fixtures/` was absent. No private
input was copied and no real LMS, player, bridge or lamp was contacted.

Validation: 2391 passed, 5 skipped in the full local Python suite; Ruff clean;
Vitest 458 passed; Playwright 74 passed; Node 22.22.2 build reproduces the
committed bundle. CI conclusions and external report provenance are recorded
in the task report after the final push.
