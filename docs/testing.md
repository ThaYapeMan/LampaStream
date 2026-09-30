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
ALSA editor field. The real SHM integration builds yeney-player at `13e606f` and
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
