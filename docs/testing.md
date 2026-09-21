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

Run the single-build helper with temporary build and installation directories:

```sh
BUILD_DIR=/tmp/lampastream-producer-build INSTALL_DIR=/tmp/lampastream-producer-bin \
  bash scripts/build-squeezelite.sh
```

It clones the shared `ThaYapeMan/squeezelite` fork at
`9a346227e9c3314bfdd15e9b189ddf5a8ab00899`, which already includes the v1 producer
and preserves the legacy PCM offsets. It inspects `make -n OPTS=-DVISEXPORT`,
compiles both producer objects, links and installs one binary. The fork integration
test checks the pinned source for producer markers and the trailing extension.
A successful build is not live SHM validation on the deployment target.

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
