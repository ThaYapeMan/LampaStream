# Testing and acceptance

## Complete local checks

From the repository root in the development environment:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -v -p no:cacheprovider
python3 -B -m ruff check --no-cache .
cd web
npm test
```

Report passed/failed/skipped totals and warnings. Frontend unit tests are separate
from Playwright end-to-end tests. Native skips are pending evidence, not failures or
successful native execution. Restricted environments may prevent TestClient/network
checks; report and rerun with appropriate permissions rather than claiming a subset.

`tests/test_latency_retirement.py` reproduces the two final blockers on `841ca873`:
real CAVA scheduling + real BeatDetector delayed output, delayed feed/EOS intervals,
bounded historical bars, and actual manager teardown while a reader remains blocked.
Only the CAVA native execution boundary is substituted. The test releases the reader,
verifies exactly-once cleanup, then verifies a new worker processes decoded PCM.

`tests/test_live_snapshot_cleanup.py` distinguishes delivery history from the freshest
live snapshot, including equal-interval ties, epochs and delayed EOS. It also exercises
repeated manager teardown with a blocked reader and an owned follower task, verifies
cleanup errors propagate, and checks subsequent activation. Historical Beat records
must survive in the queue; they need not replace a newer live Spectrum snapshot.

## Producer checks without deployment

Initialize and build the pinned producer without deployment:

```sh
git submodule update --init --recursive
make -C third_party/yeney-core yeney-player
third_party/yeney-core/yeney-player --help
python3 -m pytest -v -s tests/test_yeney_player.py
```

Build prerequisites are g++, make and libflac-dev (gcc also compiles ALAC sources).
The integration test builds an isolated copy, reuses the submodule's `tests/fake_lms.py`,
and reads real SHM through the unchanged SqueezeliteShmStereoSource(require_v1=True).
A missing toolchain prints an explicit SKIP line. No real LMS or ALSA device is needed.
Local continuity evidence does not replace live deployment validation.

## Offline acceptance

```sh
PYTHONPATH=src python3 scripts/run_acceptance.py --help
PYTHONPATH=src python3 scripts/run_acceptance.py --input music.wav --output /tmp/v2.csv --backend v2
```

Use `--backend cavacore` only where the native engine is available. Choices come
from the registry; no unknown-ID fallback exists. The harness calls public pipeline
feed/EOS, captures returned PublicationRecords, and uses canonical source extent for
`source_duration_s`. V2 warmup cannot shorten it; CAVA padding cannot lengthen it.

CSV rows expose delivery sequence, epoch, sample_start/end, effective engine,
effective_processor_ids and carried_spectrum_start/end. `t_s` is sample_start/48000.
**Rows are in delivery order, not necessarily increasing t_s**: delayed Beat results
retain their event time. Do not calculate duration from rows × hop or last timestamp.
Blank carried fields mean no historical bars were attached. Empty bars are permitted
when no eligible Spectrum history exists. Shared STFT metadata is separate from
CAVA's 4096/8192 Hann FFT and 480-frame/100 Hz execution metadata.

## Evidence labels

**CODE-VERIFIED:** deterministic local source/regression checks and successful compiler
outputs explicitly recorded with their commands.

**REQUIRES LXC VALIDATION:** native CAVA/FFTW stress, full target producer link, live
SHM continuity, clean wheel installation, realtime backlog and visual A/B. No local
stubbed test or historical benchmark substitutes for these checks.

## Clean CI bootstrap

Start with [development setup](development.md#environment), including the shared
native system prerequisites and `pip install -e '.[dev]'`. CI runs Ruff and the
complete pytest suite on Python 3.11/3.12/3.13, and also builds a native wheel.
The `build-frontend` job uses Node 22.22.2 and runs these commands in `web/`,
in this order:

```sh
npm ci
npm test
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

`npm test` runs Vitest with Testing Library for unit/component tests.
`npm run build` runs TypeScript checking and Vite's production build. Playwright's
`webServer` runs `npx vite preview` against `src/lampastream/webui`, so the build must
precede e2e execution. The current Playwright config has no browser projects or
browser override; it uses Chromium. Browser installation includes its system
dependencies and requires package-install privileges. The final CI step checks
tracked and untracked bundle differences against the committed assets.

Declared test dependencies in [web/package.json](../web/package.json) are
Vitest `^5.0.0`, Testing Library React `^16.3.3`, jest-dom `^7.0.1`, user-event
`^14.6.7`, and Playwright Test `^1.62.1`. These are version ranges;
`npm ci` installs the exact resolutions in `web/package-lock.json`.

Run these same commands before pushing; a pre-existing environment can hide missing
dependencies. Optional/native skips are reported as skips, not runtime proof.

The package list in `scripts/native-build-packages.txt` is intentionally smaller
than the target installer stack. `--check` remains a booted Debian 13/systemd
installation check, not a generic CI bootstrap.


Auto latency regressions live in `tests/test_auto_latency.py`: median/outlier
rejection, scaled MAD, initial steps and 50 ms limits, transition guards,
burst/steady cadence, Player Delay/trim arithmetic, negative residual re-alignment,
persisted starting values, sync-group fallback and a real fake CLI server that
allows only measurement position/preference commands. Migration tests verify exact
backups, reserved-field retirement and idempotency; API tests reject writable
measurement fields and invalid trims. `web/src/__tests__/Latency.test.tsx` and
`web/tests/e2e/latency.spec.ts` exercise Auto status, trim, fallback and the removed
ALSA editor field. The real SHM integration builds yeney-player at `45779a4` and
reads it through the unchanged strict-v1 PCM consumer.

Another repository may run tests concurrently on the development machine. If the
CAVA per-hop timing test fails, repeat that test alone and report both results;
do not weaken its threshold or change DSP to compensate for host contention.

## Light timing and installer pin updates

`web/src/__tests__/LightTiming.test.tsx` covers all seven timing states, automatic
entry creation and strategy switching, collapse persistence (including unavailable
storage), trim steps and limits, optimistic updates, confirmations and save errors.
Now Playing tests assert that Sync master and Delay no longer appear in Status.
`web/tests/e2e/light-timing.spec.ts` uses the preview websocket fixture to fold,
reload, retain the folded choice, save Earlier twice as −20 ms and switch Fixed
to Auto. Build the bundled frontend before running Playwright.

Backend tests check that accepted samples are timestamped, bounded to seven,
cleared with the estimator window, detached from the estimator and rejected on
API writes. The estimator and LMS command contracts remain covered by the existing
latency tests. Rerun timing-sensitive failures alone before diagnosing a regression.

The repository installer test creates real local Git repositories with a recursive
submodule and a moved parent gitlink while leaving the submodule checkout on its
old revision. Normal installation must update recursive submodules before checking
cleanliness. Separate cases must refuse genuine parent, submodule and nested
submodule edits and preserve them. `--check` remains a read-only verification;
`scripts/update.sh` pulls and delegates this ordering to the installer.

### AirPlay timing

AirPlay timing tests cover read-timestamp provenance, bounded median/MAD
processing measurements, delay arithmetic/smoothing/persistence, delivery
cadence and fallback, the diagnostic probe and conservative receiver editing.
A fake FIFO has exactly one reader; the probe consumes the diagnostic tap.
Frontend coverage exercises AirPlay states, Details and Latency Auto.

Run the backend with `pytest -v -ra` to include every skip reason. Optional
FFmpeg round-trip acceptance tests skip when no usable FFmpeg is available;
this adds four skips to environments that otherwise report four. CAVA and
soundfile availability and data-dependent reference warm-up skips are reported
individually. Native timing tests should run with BLAS thread counts limited to
one; rerun timing-sensitive failures alone before diagnosing a regression.
The owner probe is documented in [AirPlay timing](airplay-timing.md).

In this WSL environment, the eight skips are:

* `test_calib_audio.py` at collection: `soundfile not installed` (one module skip).
* `TestCavaRunnerIntegration::test_runner_uses_fifo_method`,
  `test_runner_produces_frames` and `test_runner_surfaces_stderr_on_error`:
  `cava binary not installed` (three skips).
* `test_ffmpeg_decode_roundtrip`, `test_ffmpeg_full_pipeline`,
  `test_ffmpeg_deterministic_via_file` and `test_ffmpeg_start_duration` in
  `test_run_acceptance.py`: `ffmpeg not available` (four skips).

The latter four explain the difference from an environment with only the four
soundfile/CAVA skips. No AirPlay timing test is skipped.

## Replay chain and trace format

`scripts/replay_chain.py` drives the complete offline chain: local decode →
AudioCanonicalizer → CanonicalAnalysisPipeline/processors → EnergyInput →
LayerMixer → both Effect renderers → the **actual SyncEngine.run** route →
TraceOutput. It starts no source worker, player, audio device, bridge or network
service. `scripts/run_acceptance.py` and its existing interface are unchanged.

```sh
.venv/bin/python scripts/replay_chain.py \
  --input tests/fixtures/replay/clicks-120.wav \
  --config tests/fixtures/replay/default-config.json \
  --route normal --render-hz 30 --seed 0 --out /tmp/replay-normal
# Select timestamped playback with simulated 1.5-second lookahead:
.venv/bin/python scripts/replay_chain.py \
  --input tests/fixtures/replay/clicks-120.wav \
  --config tests/fixtures/replay/default-config.json \
  --route timestamped --lead-s 1.5 --out /tmp/replay-timestamped
```

Integer PCM WAV (8/16/24/32-bit, mono/stereo) decodes with Python's wave module,
without ffmpeg. Other local formats use run_acceptance's ffmpeg decode to 44.1 kHz
S16 stereo. Record decoder/version; different lossy decoders or resamplers are
not interchangeable input evidence. `--start` and `--duration` select seconds in
the input; trace sample zero is the beginning of that selected interval.

`--config` accepts the full `GET /api/config/export` JSON envelope or its inner
`configuration` (current schema). It resolves references with production profile
builders, including manual EnergyProfile/palette choices and high/low Effects.
For a multi-coupling export, select `--coupling-id`. It also accepts a compact
object with `analyser`, `high_effect`, `low_effect`, `energy_profile`, `coupling`;
fields inside each use the API names, with model defaults for omitted values.
A compact omitted low Effect uses a default Effect; an exported empty low-effect
reference retains production's high-as-low fallback. No MusicDirector lookup is
run: replay holds the selected configuration fixed. Export is sensitive; keep real
credentials/configuration private and never commit them.

The owner can export from an already running instance with **GET
`/api/config/export`** (or the UI's Backup and restore export). For example, on an
authorized operator machine: `curl --fail http://HOST:8420/api/config/export -o
private-config.json`. This task does not contact that endpoint or any real host.
A fresh empty Storage contains palettes but no playable coupling; the committed
default export is populated locally with default model entities and a reference
coupling, without activation or credentials. It is not an export of the owner's
running setup.

`--room` reads a JSON object `{"channels":[{"channel_id":0,"position":[x,y,z]}]}`
or the channels array directly; positions can also be `{x,y,z}` objects. IDs are
unique integers 0–255 and coordinates are finite. The committed two-channel room
is a **synthetic** left/right fallback, not a claim about owner-area coordinates.
Supply the owner's area positions through this file for physical comparisons.
TraceOutput samples the same Scene protocol as HueDriver and matches
hue-entertainment 0.1.2's command-to-wire conversion, including its unusual
pass-through branch for 16-bit command values <=255.

`--render-hz` accepts 20, 30 (default), 50 or 60. Only the offline process scopes
SEND_INTERVAL_S to this rate; production still defaults to 1/30. Sleep advances a
fixed tick index, not an accumulating float or real asyncio timer. DSP runs in
fixed source chunks with at most one shared hop per feed; publications are then
released through the pipeline's real publication method into the output loop.
Epoch UUID labels are normalized to `replay-0001`; no DSP algorithm is replaced.

`--publications-per-tick=0` (default) releases all records whose availability time
has arrived; a positive value caps delivery at that many per tick, creating a
reproducible backlog. It never releases future records early. `--delay-ms` sets
the normal-route probe; `--delay-schedule '[[0,500],[5,0]]'` changes it at virtual
seconds, preserving today's burst-on-shrink behavior. `--lead-s` (default 1.5)
sets simulated timestamped play time relative to the reported sample. Normal
playback does not use this lead; timestamped playback ignores the normal-only
delay and delay-schedule options. A post-input tail covers delay/lead and two render
intervals; the normal route deliberately retains production's terminal latest
snapshot while the tail is rendered.

### Deterministic encoding and clocks

Version 1 writes six files, stable column order, UTF-8, LF newlines, sorted JSON
keys, six-decimal finite floats and empty CSV cells/JSON null for absent or
nonfinite values. Per-channel CSVs have one row **per channel**, with a shared
render/send ID; count IDs, not rows. List-valued cells contain compact JSON.
Seeds cover global Python/NumPy and per-renderer band shuffle/random/mix RNGs;
splotch seeds and fireworks origins retain their deterministic production logic.
No wall timestamp, absolute path, random UUID or measured runtime enters traces.

Identical bytes/config/options/revision and Python/NumPy/decoder/native versions
produce byte-identical files. Run twice and compare every file's SHA-256. Across
machines, compare the same dependency/runtime versions; meta deliberately records
version differences, so it cannot be byte-identical across differing versions.
Six-decimal encoding suppresses sub-precision representation noise; it does not
promise numerically identical DSP on every CPU/native-library combination. Use
native WAV fixtures for cross-machine regression checks, not lossy decode.

`meta.wall_time` explicitly describes the **virtual wall timeline**, not measured
CPU execution: `{basis:"virtual",start_s:0,end_s:...}`. Actual execution wall time
is printed to stderr separately, because embedding it would contradict the
requirement that every trace file hash match. The replay models zero computation
cost between virtual boundaries; it cannot benchmark real CPU scheduling.

Time-chain coverage follows [measurement-protocol.md](measurement-protocol.md):
**1** sample/event reporting and candidate positions; **2** shared window reference;
**3** simulated detection availability and publication; **4** render/scene targets;
**5** virtual send calls. Points **6–7**, audible sound and measured light, require
physical capture and are not present. Virtual send is not DTLS transmission or
lamp response. Integer sample positions are at canonical **48,000 frames/s**;
intervals are half-open. Epoch labels are separate from the clock. All `*_time_s`
values are virtual monotonic seconds since replay start, never Unix timestamps.

### features.csv — one row per publication, in delivery order

It retains every run_acceptance column (and extra `bar_NN` columns when configured
above 30 bars):

| Columns | Meaning / units |
|---|---|
| `t_s` | Reported `sample_start/48000`, audio seconds; not publication time. |
| `backend`, `effective_backend`, `effective_engine` | Requested and effective Spectrum engine identifiers. |
| `bar_00` … `bar_29` | Normalized Spectrum values, normally [0,1]; absent bars are blank, not fabricated future bars. |
| `bass`, `mid`, `full`, `centroid` | Production scalar aggregates/normalized centroid. |
| `onset`, `onset_bass`, `onset_mid`, `onset_treble` | Reported flags, 0/1; aggregate is independent from band identities. |
| `onset_strength`, `onset_bass_strength`, `onset_mid_strength`, `onset_treble_strength` | Existing current-frame raw ODF values, not corrected candidate strengths. |
| `relative_exertion` | Existing alias of full energy. |
| `peak_ema`, `bars_smooth_mean`, `bars_smooth_max` | V2 diagnostic peak reference and falling-bar state at feed; zero when unavailable. |
| `sequence`, `epoch`, `sample_start`, `sample_end` | Delivery sequence, normalized epoch, exact canonical reporting interval. |
| `effective_processor_ids` | Semicolon-separated fresh contributors. |
| `carried_spectrum_start`, `carried_spectrum_end`, `carried_historical` | Historical bars' interval (blank if absent) and 0/1 carried marker; carried bars are not fresh contributions. |
| `availability_sample` | Canonical input frontier when feed/EOS returned this record; source-frame availability boundary before delivery batching. Does not measure resampler/CPU latency. |
| `publication_time_s` | Virtual tick at which the record was released to consumers, after any delivery cap/backlog. |
| `received_time_s`, `play_time_s`, `timing_generation` | Original source-read/play provenance and generation; these are not detection/publication times. |
| `level`, `loudness_momentary_lufs`, `loudness_short_term_lufs` | Raw stereo RMS and K-weighted LUFS; blank for unavailable/nonfinite readings. |
| `sustained_energy`, `hpss_active`, `percussive_energy`, `harmonic_energy` | Existing sustained scalar, 0/1 HPSS validity and fractions. |
| `event_id_B` | For B=`all,bass,mid,treble`: one ID `epoch:band:reported_sample` for each positive flag, blank otherwise. Aggregate and band events must not be summed as distinct physical clicks. |
| `candidate_sample_B`, `candidate_strength_B` | Buffered peak-candidate window start (canonical sample) and its own raw ODF, observed without changing the picker. Blank before observer history is ready or when that band is not implemented. |
| `reported_sample_B`, `reported_strength_B` | Current shared-hop start and raw ODF returned today; intentionally retain the candidate/current-frame mismatch. |
| `decision_sample_B` | Current window completion (`reported_sample+2048`), distinct from candidate start and rounded feed availability. |

For multiband, `all` candidate diagnostics follow the band with maximum current
raw strength, matching the existing aggregate-strength convention. Picker
diagnostics on non-onset rows are context, not extra detected events. Ground
truth remains in fixture sidecars and is not substituted for detector decisions.

### energy.csv — one row per output-loop tick

| Columns | Meaning / units |
|---|---|
| `tick`, `virtual_time_s`, `route` | Zero-based tick, virtual time, normal/timestamped route. |
| `energy_source`, `energy_value` | Selected EnergyInput mode and scalar after the tick's last render; initial zero before any render. |
| `mix_target`, `mix` | Cubic smoothstep target and actual EMA-smoothed mix after the tick's last render. Timestamped ticks may perform multiple renders/EMA steps. |
| `adaptive_floor`, `adaptive_ceiling`, `peak_envelope` | EnergyInput state (LUFS bounds, amplitude envelope), not recomputed by observers. |
| `consumed_sequences`, `render_ids` | Ordered lists of actual mixer reads/renders this tick, including repeated reads. |
| `delivered_sequences` | Publications first made available this tick, including ones subsequently skipped. |
| `repeat_reads` | Actual reads this tick after a sequence was previously rendered. |
| `consumed_count`, `repeated_count`, `skipped_count` | Disjoint final classification of publications delivered this tick: rendered exactly once, more than once, or never. This post-run ledger sums to the number published. |
| `consumed_publication_sequences`, `repeated_publication_sequences`, `skipped_publication_sequences` | Sequence lists behind those disjoint counts. A repeated publication is counted once here, not once per duplicate read. |

Thus **consumed + repeated + skipped = published** is a publication-identity
partition; actual render reads are recorded separately and can exceed published.
This prevents repeated flags from disappearing behind an ambiguous count.

### renders.csv — one row per mixer render and room channel

| Columns | Meaning / units |
|---|---|
| `render_id`, `sequence`, `channel_id` | One-based scene/render identity, consumed publication and room channel. Both layers render once per mixer invocation. |
| `virtual_time_s`, `render_argument_s`, `route` | Actual virtual invocation time, time argument passed to the renderer, route. For early rendering the argument can be future play time; it is not detection availability. |
| `play_time_s`, `scheduled_play_time_s`, `schedule_target_s` | Timestamped intended play time (two explicit aliases) and `max(ready,play)` target with zero replay trim; blank on normal route. Sending is quantized to the first tick at/after target, not guaranteed within half a tick. |
| `event_ids`, `onset_consumed` | IDs carried by this render and aggregate flag 0/1; repeated flags remain visible. |
| `high_effect`, `low_effect` | Effect type identifiers used by the two layers. |
| `r`, `g`, `b` | Scene Colour sampled at this room position and render argument, in floating RGB units before driver clamping. |

### sends.csv — one row per actual virtual send and room channel

| Columns | Meaning / units |
|---|---|
| `send_id`, `scene_id`, `channel_id` | One-based send identity, originating render identity, room channel. |
| `virtual_time_s`, `route`, `generation` | Send-call time, originating route, timing generation (timestamped=1; normal output generation=0). |
| `r`, `g`, `b` | Scene sampled at send time, as HueDriver does; can differ from render-time colours for moving scenes. |
| `r8`, `g8`, `b8` | Effective bytes in Hue RGB 0x00: clamp/convert to 16-bit via Colour.to_16bit, then `v>>8` if v>255, otherwise v, with upper clamp 255; dependency duplicates each byte into two wire bytes. |
| `interval_ms` | Time since preceding **send**, not preceding channel row; blank for first send, zero for same-tick bursts. |
| `event_ids` | Originating publication's flag IDs, for correlation even when final light brightness hides an event. |

A carried ID is attribution, not proof of an observable flash. Normal delay shrink
bursts and timestamped coalescing are observed, not repaired.

### counters.json and meta.json

`counters.events` has entries `all,bass,mid,treble`. For each, `received` is unique
positive flag IDs published, `accepted` unique IDs reaching the mixer, `rendered`
counts render occurrences (including repeats), `merged` counts unsent IDs whose
scenes were coalesced by the timestamped scheduler, `expired` counts other accepted
but unsent IDs, and `lost` counts received IDs absent from every sent scene.
An ID seen in any sent scene is not merged/expired/lost even if another copy was
coalesced. Rejected picker candidates are not counted as received events.

`publications[route]` contains `published`, the disjoint `consumed/repeated/skipped`
identity counts, `render_reads` and `repeat_reads`. `sends` counts send calls;
`sends_per_second.{p50,p95,max}` uses integer virtual-second bins including idle
and partial edge bins, NumPy's linear percentile convention. `publication_queue_drops`
records actual bounded-queue evictions during route replay (not DSP precomputation).

`meta.json` contains `trace_version`, `quantization_decimals`, SHA-256 of original
input/config/room bytes, decoded `format` (encoding, bits, channels, sample_rate,
plus decoder/version for ffmpeg), selected canonical `duration_s`, full `git_commit`,
`seed`, `route`, `render_hz`, `publications_per_tick`, `delay_ms`, `delay_schedule`,
`lead_s`, `start_s`, `python_version`, `numpy_version` and explicit virtual
`wall_time`. Input hash covers the whole file even when selecting a clip. It
contains no exported credentials or absolute private paths. Keep the CSVs local;
only synthetic reference counters/meta are committed under `docs/baseline/traces/`.

### Synthetic replay fixtures

Regenerate with `.venv/bin/python scripts/make_fixtures.py`. The complete set,
sidecars and default export is **9,083,505 bytes**, below 10 decimal MB. The three
10-second 120/128/174 BPM centre-mono click files are 48 kHz, 24-bit PCM. Clicks
start at 0.5 s, after detector warmup, and stop before EOF. The single impulse is
48 kHz/16-bit, at sample 240000 (5.000 s) in a six-second file. The 1 kHz stepped
tone is 48 kHz/16-bit with two-second peak-amplitude segments at −30/−20/−10/−3
dBFS. Silence is three seconds at 48 kHz/16-bit.

The 20-second 20 Hz–10 kHz logarithmic sweep, five-second seeded Voss-McCartney
pink noise, ten-second anti-phase and ten-second left-to-right panning click files
use 24 kHz/16-bit PCM, deliberately exercising canonical resampling while keeping
the committed set small. Anti-phase integer PCM satisfies L=−R exactly. No
copyrighted recordings or external samples are used.

Each same-stem JSON contains `fixture_version`, `sample_rate`, `channels`, `bits`,
`frames`, `event_samples` (source-rate sample indices) and `description`. Click
positions and the impulse are sparse truth; tone indices label amplitude-segment
boundaries, not asserted detected onsets. Continuous sweep/noise and silence have
empty sparse truth lists. They do not assert that a detector must emit no events.
`default-config.json` is generated with production `export_configuration` from a
fresh local Storage populated with default model entities; fixed provenance time
and BASE-01 revision make regeneration independent of the generator's run date.

## Regression pairs (pin_current / contract xfail)

REG-01 adds `test_onset_picker_regression.py`, `test_onset_position_regression.py`,
`test_onset_strength_regression.py` and `test_event_survival_regression.py`.
Every behavior has two views:

- `test_pin_current_<name>` asserts the measured current numbers. Its docstring
  names TIME-01 or EVENT-01, the ticket expected to change or preserve that pin.
- `test_contract_<name>` asserts the intended event-position/strength or survival
  contract. Known violations use `pytest.mark.xfail(strict=True, raises=AssertionError,
  reason="TIME-01: ...")` or `reason="EVENT-01: ..."`. An unexpected success fails
  the suite; setup/type/runtime errors do not masquerade as expected assertion failures.

When a ticket lands, inspect the old pin failure, record the measured before/after,
update the pin to the new deliberate behavior, and remove the contract's xfail in
**the same commit**. Preserve the contract assertion; do not delete it, weaken the
window, or regenerate expected numbers merely to make a run green. A still-broken
contract stays marked with its owning ticket. A universal survival contract checks
all 30/60 Hz × unrestricted/cap-1 variants before asserting, so already-correct
subcases are included without falsely marking them individually as failures.

Numeric evidence is checked in as `tests/fixtures/onset-regression-numbers.json`;
its measurement anchor is **135ab38563baba1f4d5a7f2dcd67e349e5f2f88d**. Tests never
rewrite this file. Samples/counts are deterministic exact pins; hop conversions
allow one sample (1/480 hop), and six-decimal CSV strengths allow absolute 1e-6,
with relative tolerance disabled. Spearman uses NumPy average ranks for ties;
constant ranks return `None`, not an invented zero correlation.

Default replay configuration uses the combined detector, whose bass/mid/treble
flags are unavailable. Those empty bands are explicitly pinned. A second variant
changes **only** `onset_method` to multiband to measure independent band behavior.
The generic picker probe also covers the Dixon picker shared by SuperFlux; the
existing BENCH-01 tests still check all three processor paths without modification.

Ground truth is converted from sidecar source-rate indices to 48 kHz canonical
samples. Each truth event finds the nearest availability and nearest candidate
**independently**, with ties choosing the earlier delivery. Signed offsets mean
observed minus truth. Tables report signed medians and maximum absolute offsets.
Both coordinates separately count misses and false positives outside ±2 hops.
These are **alignment-window** misses: 19 detected clicks can still have 19 such
misses because their candidate window starts precede the actual click by 3–4 hops.
They must not be described as 19 failures to detect audio.

Panning divides truth clicks into `<5 s` left-biased and `>=5 s` right-biased
halves, yielding nine and ten clicks. It pins both positions and strengths rather
than assuming equal amplitudes. Anti-phase stereo retains real detection; the
contract also requires event-aligned candidate attribution, which remains broken.
Tone-step level association uses the nearest transient within 100 ms of each
step. The first level starts during warmup and has no detected onset: a separate
presence flag is false, with zero only as a diagnostic placeholder for four-level
rank calculation, never a fabricated event. Combined/multiband aggregate tone rho
is already **1**; its paired contract additionally requires candidate-attributed
strength. The multiband bass reports zero strengths and has undefined rho.

Replay tests import the harness and use module-scoped access to one shared
session cache per `(fixture, method, route, rate, delivery cap)`. DSP is computed
once per fixture/method; route variants deep-copy the same returned records into
fresh production publication/mixer/output state. Every pipeline is closed. CSV
files remain in pytest temporary storage; no network, audio devices or lamps are
used. Cache construction does not alter production or BENCH-01 source files.

Runtime check (Python 3.12.15, BLAS threads=1, affinity to one CPU): **103 passed,
133 strict xfailed in 40.34 s** for all four new modules. The position module alone
was **23.81 s**, below its approximately 60-second budget; the combined added
suite is below approximately 90 seconds. No slow marker or CI exclusion is needed.
Run the four files together to retain session-cache reuse. An example one-core run:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python - <<'PY'
import os
import pytest
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
raise SystemExit(pytest.main([
    '-v', '-ra',
    'tests/test_onset_picker_regression.py',
    'tests/test_onset_position_regression.py',
    'tests/test_onset_strength_regression.py',
    'tests/test_event_survival_regression.py',
]))
PY
```
