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
