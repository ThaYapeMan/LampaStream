# Decision log

Phase-zero comparison baseline: **3998c440f464d0cf02743633fba98e8dd990743b**.
Each dated line records an owner decision or a bounded documentation choice for BASE-01.

- 2026-10-24 — Licence: LampaStream's own code is PolyForm Noncommercial 1.0.0, Required Notice: Copyright (c) 2026 Jaap van Vliet; third-party licences remain their own. Open question: revisit at phase 7 — switch to Apache-2.0 or AGPL-3.0 if the project wants outside contributors; possible while all copyright is the owner's.
- 2026-10-24 — Keep EnergyProfile, LayerMixer and MusicDirector; no second direction layer. These existing components remain the configuration, blending and musical-context boundaries.
- 2026-10-24 — Phase order from the owner's *LampaStream bevindingen en ontwikkelplan* (24 October 2026): baseline → measurement harness and regressions → event and time correctness → physical sync → better use of existing features → beat/phase → structure.
- 2026-10-24 — Distinguish live without lookahead, live with measured lookahead (reference AirPlay early tap approximately 1.5–2 s; LMS head start 500 ms), and whole-track accessible (not implemented); see [baseline conditions](baseline.md#information-conditions).
- 2026-10-24 — Reference setup is LampaStream LXC 112 (192.168.178.24), LMS LXC 111 (192.168.178.23), YeneY LXC 113 (192.168.178.31), Hue Bridge 192.168.178.19, lamps including Hue Iris, LampaStream LMS virtual player, AirPlay receiver, Sonos Study/Sonos Port through YeneY, Radio Red and piCorePlayer; supplied facts, not newly measured evidence.
- 2026-10-24 — Dataset policy: about 20 fragments, three per techno/house/deep house/hard dance/disco plus ambient/speech/silence/anti-phase/click controls; separate development, regression and held-out recordings, keep private music outside Git; see [measurement protocol](measurement-protocol.md#dataset-policy).
- 2026-10-24 — BASE-01 fixes comparison baseline commit 3998c440f464d0cf02743633fba98e8dd990743b; later documentation commits do not silently move that anchor.
- 2026-10-24 — Validate the frontend in an isolated archive of the comparison commit; this records real baseline totals without rebuilding or modifying the repository's web directories.
- 2026-10-24 — Split the initial musical recordings one per genre per set, place the five controls in regression, and store private-fixtures outside the checkout; this gives each set genre coverage and prevents accidental music commits without changing ignore rules.
- 2026-10-24 — Physical offset is light onset minus audible onset (positive is late light); report jitter and outliers separately so a mean offset cannot conceal instability.
- 2026-10-24 — Current Musical context/palette decisions remain in [music-colours.md](music-colours.md); earlier Players/UI decisions remain in [designs/players-decisions.md](designs/players-decisions.md), linked here rather than copied.

## BENCH-01 replay decisions

- 2026-10-25 — Keep SyncEngine's real clock/sleep defaults and SEND_INTERVAL_S=1/30; SceneSchedule already accepts explicit times, so no production scheduler API change is necessary.
- 2026-10-25 — Run the actual output coroutine with an injected tick clock; scope alternative render rates and scheduler observers only to the offline process, avoiding a second implementation of route behavior.
- 2026-10-25 — Precompute DSP at fixed source chunks, then release returned records through the real publication method at controlled ticks; normalize only the nondeterministic single-file epoch label.
- 2026-10-25 — Observe current picker candidate/current raw strengths with harness-owned wrappers, leaving production decisions and returned strengths untouched; REG-01 will define corrective expectations.
- 2026-10-25 — Use a labelled synthetic left/right room because owner-area coordinates were not supplied or found locally; --room accepts their JSON without contacting a bridge.
- 2026-10-25 — Use virtual wall time in deterministic meta.json and print actual execution wall time separately to stderr; embedding measured runtime would make identical trace-file hashes impossible.
- 2026-10-25 — Canonicalize finite trace floats to six decimals and JSON keys/newlines; byte identity requires matching runtime/dependency versions, which remain explicitly recorded rather than concealed.
- 2026-10-25 — Count consumed-once, repeated and skipped publications as disjoint identity classes; log duplicate render reads separately, so consumed+repeated+skipped=published remains meaningful.
- 2026-10-25 — Event IDs describe reported positive flags per epoch/band/sample, not ground-truth clicks; distinguish render acceptance, scheduler coalescing and actual sent-scene attribution without claiming visible lamp reactions.
- 2026-10-25 — Start click fixtures at 0.5 s after warmup; use a six-second impulse file and 20 Hz–10 kHz sweep. Use 24 kHz/16-bit sweep/noise/stereo fixtures to exercise resampling and keep all fixture files below 10 decimal MB; the three main clicks remain 48 kHz/24-bit.
- 2026-10-25 — Export a fresh local Storage populated with default model entities and one reference coupling; an entirely empty fresh store has no playable coupling. Fixed synthetic export provenance makes regeneration reproducible; no owner configuration or credentials are committed.
- 2026-10-25 — Use publications-per-tick=0 for natural unrestricted delivery; positive values cap delivery and preserve backlog rather than releasing future audio early. Normal delay options do not alter timestamped trim.
- 2026-10-25 — Require --coupling-id for multi-coupling exports instead of silently selecting an arbitrary session; accept compact API-named entities for local experiments.
- 2026-10-25 — Retain post-input terminal snapshots through the output-tail interval and count idle/partial virtual-second send bins; these reproduce current route mechanics and make the metric denominator explicit.

## REG-01 exposure audit

- 2026-10-25 — No production exposure was needed: BENCH-01's offline PickerObserver already records candidate/current raw flux and positions, while the existing private EMA attribute is sufficient for a read-only normalization probe. No production or harness return shape, value or timing changes in REG-01.
- 2026-10-25 — Input for TIME-01: OnsetDetector's public result is still only `(onset, current_flux)`; it exposes neither candidate frame nor an independent availability frame as an event record. The isolated contract probes an optional `last_event` record with candidate_frame/candidate_strength/availability_frame; this is a test-side proposed adapter, not a newly promised production API. TIME-01 must choose the representation and update/unmark that contract in the same commit.
- 2026-10-25 — Input for TIME-01: authoritative event-window reference and numeric lookahead are not yet defined. REG-01 pins every current gap and requires constancy in the intended fixture contract without inventing a new numeric latency target; current 48 kHz candidate-window-start→availability is eight hops, while resampled 24 kHz inputs have several chunk-dependent values.

## REG-01 measurement and regression choices

- 2026-10-25 — Use raw precomputed ODF through process_odf, with 50 low-flux warmup frames and a zero tail, so the isolated frame-50→53/strength-zero mismatch is unambiguous; normalization remains the picker's own computation.
- 2026-10-25 — Test silence both as a 500-frame prelude to the same peak series and as a read-only EMA decay after priming. Pin the extra low-flux transition onset as well as the unchanged three-frame peak delay, rather than assuming silence is harmless.
- 2026-10-25 — Keep the default combined configuration unchanged for reference replays; add only an onset_method=multiband override for meaningful per-band measurements. Disabled combined bands are labelled unavailable, not failures of enabled detectors.
- 2026-10-25 — Convert sidecar truth to 48 kHz sample coordinates, use independent nearest neighbours for availability and candidate, and choose earlier delivery on ties. Report signed median and maximum absolute offset; apply the requested ±2-hop window to each coordinate separately.
- 2026-10-25 — Label ±2-hop misses/false positives as alignment-window counts: all truth clicks can be detected while none match a window-start coordinate within that window. Do not confuse those counts with route event loss.
- 2026-10-25 — Split panning at 5 s (9 left-biased, 10 right-biased clicks) and pin both strengths and offsets; do not assume equal effective amplitudes or dismiss the multiband union's extra event.
- 2026-10-25 — Associate tone-step transients within 100 ms of each known level change. Startup has no detected onset; keep an explicit false presence bit and use zero only as a four-level rank diagnostic placeholder. No event is fabricated.
- 2026-10-25 — Implement Spearman with NumPy average ranks for ties; constant ranks produce undefined/None. Aggregate tone rho is already 1, so its strict xfail also asserts the genuinely broken candidate attribution; a standalone rho=1 assertion cannot honestly be labelled an expected failure.
- 2026-10-25 — Preserve BENCH-01's multiband aggregate diagnostic convention: all follows maximum current strength, with equal-zero ties selecting bass. It is not the maximum candidate-strength band. TIME-01 must decide aggregate candidate attribution rather than silently correcting the observer here.
- 2026-10-25 — Measure the full 30/60 Hz × unrestricted/cap-1 matrix for seven fixtures, both routes and both methods. Universal contracts evaluate all variants before asserting, including already-green cap-1 cases, so strict xfails describe actual remaining violations.
- 2026-10-25 — Store reviewed immutable numeric expectations in one JSON fixture, with compact numeric arrays; tests never regenerate or bless their own expectations. Exact samples/counts and absolute 1e-6 CSV-strength tolerance avoid broad relative tolerances hiding changes.
- 2026-10-25 — Share one session replay cache through module-scoped fixtures and reuse deep-copied DSP results only across route/rate variants. Fresh publication, mixer and output state preserves the production route semantics while avoiding repeated DSP work.
- 2026-10-25 — No slow marker or CI exclusion: all four added modules took 40.34 s on one CPU (103 pins passed, 133 contracts xfailed); the position module alone took 23.81 s. Existing tests are unchanged and remain in the full suite.
- 2026-10-25 — No discrepancy from BENCH-01: clicks-120 normal/30/free remains received=19, accepted=0, rendered=0, lost=19. Both routes' counters match the committed baseline byte-for-byte, and all eight CSVs match the original local BENCH-01 captures. Meta git revision necessarily changes and is not asserted identical.

## EVENT-01 detector decisions

- 2026-10-25 — Use raw-flux absolute delta 0.02 and standard-deviation floor 0.01: below the smallest fixture band transient while rejecting numerical residuals; normalized strength clips at six standard deviations.
- 2026-10-25 — Hold statistics for three ungated frames and exclude silent windows: preserve the pre-silence reference without swallowing the first transient. The legacy raw-ODF adapter treats zero flux as silence; canonical detection gates the analysis window's spectral RMS.
- 2026-10-25 — Confidence is margin/(margin+std), multiplied by candidate/max(candidate, alpha-decayed flux, std floor), then by the fraction of enabled bands firing. Alpha reduces confidence without suppressing peaks.
- 2026-10-25 — Candidate sample uses the causal flux attack reference, three hops after the leading STFT window position; availability is a separate hop coordinate with explicit configured lookahead. Input batching never selects lookahead.
- 2026-10-25 — The web Analyser and Effect TypeScript interfaces will require the optional new API fields in the Styles phase; no frontend files are changed here.

- 2026-10-25 — Queue overflow increments events_dropped_count rather than blocking audio; event IDs remain candidate identities, independent of publication polling. The bounded queue is 1000 records, with the same publication lock.
- 2026-10-25 — Undeclared outputs use 30 Hz, 16-bit colour, zero estimated transport latency, two-frame minimum hold and shared channel timing. This preserves generic test outputs while making driver-specific precision and timing explicit.
- 2026-10-25 — Quantisation guarding belongs to output_boundary.py: eight output codes above idle baseline, with sub-code decay held. Idle scenes pass through byte-identically; renderers never choose transport precision.
- 2026-10-25 — TriggerEnvelope retains bounded event-time history so pre-rendering timestamped scenes cannot accidentally expose future triggers. Within a render burst, the strongest event drives the envelope; identities and the event count are retained.
- 2026-10-25 — Normal-route event time is backdated from the freshest canonical sample extent at intake; timestamped events use candidate play time minus onset_lead_s. Expiry is evaluated against the scene clock.
- 2026-10-25 — Onsets remain invisible in the default spectrum_rgb configuration because onset_flash_intensity is 0.0. Changing that visible default belongs to the Styles phase. Continuous bars and idle output retain their existing arithmetic.
- 2026-10-25 — RENDER-01 retains ownership of all non-onset per-tick energy, palette, particle and spatial ballistics; only flashes/pulses switch to the shared time envelope here.
- 2026-10-25 — Partial multiband votes wait for the earliest candidate's 30 ms window; a complete three-band vote can finalize immediately. Aggregate strength_raw is the largest raw band candidate flux, independently of which band's normalized flux dominates.
- 2026-10-25 — Statistics updates wait until the candidate decision and exclude high-flux attack frames after warmup; otherwise the frames preceding a confirmed peak still train its own normalization reference. The exact isolated 50-frame EMA pin becomes 0.19885471662059553.
- 2026-10-25 — Replay publication delivery caps throttle only continuous publications. Available events use their independent transport; deliberately delaying the event queue behind the publication cap would reproduce the defect the new queue removes.
- 2026-10-25 — Software timing limitation: the shared 2048-sample STFT still needs its complete window. Candidate/confirmation coordinates do not remove that acquisition delay. Phase-two clicks-174 normal/30 first-send offsets reach about 66 ms; the requested one-render-interval-plus-lookahead bound is not established by the event-queue fix. Timestamped first sends also retain hop/render quantization. No physical latency result is inferred from the replay.
- 2026-10-25 — `web/src/lib/api.ts` Analyser (line 240) and Effect (line 257) interfaces do not yet list the new optional fields; the backend API/config export accepts them. This ticket leaves both frontend trees untouched.
- 2026-10-25 — Event counters in the replay are recomputed from unique emitted IDs and intake dispositions, independently of increment counters. A missing or still-pending identity counts as lost, so a zero cannot conceal queue transport loss.
- 2026-10-25 — Preserve the legacy adapter's current raw flux on non-event frames for existing callers; on an event frame it returns the candidate raw flux. Renderer-facing onset_strength instead carries the newest event's normalized strength.
- 2026-10-25 — Cache immutable numeric fixture sections during the regression session. Exact pins remain committed and are never regenerated by tests; this avoids reparsing the larger phase-two fixture on every assertion and limits suite wall time.
- 2026-10-25 — Preserve the candidate source-read clock internally before overwriting received_monotonic with the drain clock. Normal envelopes use that source clock when available; only sources without receipt provenance fall back to latest-extent backdating. Polling delay must not move the event anchor.
- 2026-10-25 — Beat-only candidate publications neither replace the continuous latest snapshot nor advance timestamped render ballistics. Their events travel through drain_events. Thus publication flags can be skipped while all event identities survive; otherwise the candidate reference could temporarily freeze fresh Spectrum bars or advance layer EMA an extra time.
- 2026-10-25 — Compared the default zero-intensity clicks-120 normal/30 output directly with an isolated e03f1a8 replay: all 602 per-channel send colours and timestamps are byte-identical after separating continuous publications.
- 2026-10-25 — The in-process regression matrix skips serializing its unused renders.csv/sends.csv files while still executing and sampling every production render/send and computing the same identities/dispositions. Ordinary CLI replay always writes all seven files. This removes redundant diagnostic serialization from CI without excluding any scenarios or assertions.
- 2026-10-25 — Precision guarding also covers the intrinsic onset styles in either layer, not only an explicit white-flash intensity. Guard only positive lifts above baseline so unlit colour channels and spatially dark positions remain dark.
- 2026-10-25 — An omitted capabilities hold derives from the declared update rate (two frames), while a completely undeclared output retains the conservative 30 Hz profile. Reject nonfinite capabilities so an invalid rate cannot silently disable the visibility hold.

## LAT-01 decisions

- 2026-10-26 — Start from pulled 542b9ed; preserve the existing untracked design image.
- 2026-10-26 — Split measured input-frontier delay into exact hop rounding, explicit picker lookahead and residual window acquisition; candidate coordinates alone cannot measure acquisition.
- 2026-10-26 — Match latency rows only within 100 ms of sparse sidecar truth; retain unmatched events to expose false positives rather than fabricate truth.
- 2026-10-26 — The short front end emits one right-aligned frame at each 10 ms boundary, with zero history only at epoch start; its hop coordinate is the preceding hop start. Long-window bass retains its three-hop attack reference. Existing callers without short frames retain their legacy analysis path.
- 2026-10-26 — Raw short-window pink-noise detections rose 79→82, so use 24-band/octave mean magnitude followed by log10(1+X), collapsing unresolved duplicate bin boundaries. This reduced the count to 80 (77 trigger groups), without increasing thresholds; sweep 309→303. Sparse empty truth labels all noise events as unmatched, not proven perceptual false alarms.
- 2026-10-26 — Retain lookahead 1 as default: lookahead 0 adds two unmatched pink-noise events (82 vs 80) and five sweep events (308 vs 303). Click recall and double hits are unchanged; both 0 and 1 remain selectable. No threshold adjustment.
- 2026-10-26 — Keep default cadence 30 Hz despite measured >11× one-core margin at 50 Hz: extra sends already meet the normal latency goal and continuous effect ballistics remain cadence-dependent until RENDER-01. output_render_hz is a validated 20–60 Hz analyser/profile setting; the harness sets it explicitly.
- 2026-10-26 — Poll the lossless event queue every ≤5 ms between cadence deadlines; this bounds software wake delay without cross-thread loop callbacks or a second output task. Deferred extras coalesce through SceneSchedule and obey 1/(2×output.update_hz); delayed continuous slots retain the historical delay-shrink behavior.
- 2026-10-26 — Omit empty short-front-end BeatDetector updates: they only duplicated cleared compatibility flags on independent intervals, increasing queue churn. Continuous snapshots keep their cleared defaults; positive candidate publications remain explicit.

LAT-01 preliminary one-core trace headroom, BLAS threads=1. Loop times include
observer overhead, measured between injected sleeps; total core % includes DSP.
Backlog is pending replay publications at completion; publication evictions on the
normal route are unused snapshots, distinct from event drops. The redundant empty
short-hop publications were removed after this measurement.

| Fixture | Route | Hz | DSP ms/hop | Loop p95 / max ms | Total core % | Margin | Backlog | Pub / event drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pink-noise | normal | 30 | 0.707 | 0.133 / 0.777 | 7.8 | 12.78× | 0 | 0 / 0 |
| pink-noise | normal | 50 | 0.687 | 0.131 / 0.972 | 7.7 | 12.98× | 0 | 0 / 0 |
| pink-noise | normal | 60 | 0.685 | 0.126 / 1.040 | 7.8 | 12.79× | 0 | 0 / 0 |
| pink-noise | timestamped | 30 | 0.683 | 0.409 / 1.175 | 7.9 | 12.70× | 0 | 0 / 0 |
| pink-noise | timestamped | 50 | 0.693 | 0.295 / 0.412 | 8.1 | 12.38× | 0 | 0 / 0 |
| pink-noise | timestamped | 60 | 0.767 | 0.261 / 0.856 | 8.9 | 11.24× | 0 | 0 / 0 |
| clicks-174 | normal | 30 | 0.778 | 0.126 / 1.192 | 8.4 | 11.92× | 0 | 996 / 0 |
| clicks-174 | normal | 50 | 0.779 | 0.131 / 1.521 | 8.6 | 11.64× | 0 | 996 / 0 |
| clicks-174 | normal | 60 | 0.788 | 0.129 / 42.696 | 9.3 | 10.80× | 0 | 996 / 0 |
| clicks-174 | timestamped | 30 | 0.795 | 0.419 / 0.639 | 9.0 | 11.11× | 0 | 0 / 0 |
| clicks-174 | timestamped | 50 | 0.778 | 0.252 / 1.410 | 9.0 | 11.15× | 0 | 0 / 0 |
| clicks-174 | timestamped | 60 | 0.797 | 0.246 / 1.369 | 9.2 | 10.88× | 0 | 0 / 0 |
- 2026-10-26 — Timestamped scenes wake at min(next cadence deadline, next scheduled deadline), retaining SceneSchedule coalescing and generation fencing. Add explicit event-boundary renders at candidate playback minus onset_lead_s, because merely waking accurately still leaves continuous-hop quantisation. Positive onset_lead_s retains its existing meaning: advance light before audio, not delay it.
- 2026-10-26 — Exact scheduling is measured against the candidate's lead-adjusted playback clock; candidate-to-truth uncertainty is separately visible in latency.csv. The scheduler does not use fixture truth. Accept only 1e-10 seconds of comparison tolerance at heap deadlines to avoid a floating-point boundary causing a spurious microsecond wake.
- 2026-10-26 — Use POSIX advisory locks and session-local disk artifacts for xdist sharing; pickle only locally generated DSP snapshots, with source/input/config/options hashes. Cache reference replays across BENCH-01 and regression tests, while cross-process determinism probes still execute independent subprocesses.
- 2026-10-26 — Retain only the feature/energy columns consumed by regression assertions in the in-memory cache; retain complete CSVs on disk. This bounds memory while preserving reviewable evidence.
- 2026-10-26 — Continuous timestamped scenes keep their original cadence quantisation; only event boundaries add precise deadlines. Use strict source-target versus cadence comparisons when assigning continuous slots, preserving phase-two floating-point boundary choices and idle colour bytes.
- 2026-10-26 — Publication delivery caps remain per render interval despite the new intermediate wakes; event release remains independent. Otherwise cap-1 replay would silently become a faster delivery configuration.

- 2026-10-26 — GitHub rejected the CI workflow edit because the configured token lacks workflow scope. Configure pytest addopts=-n auto instead: the existing CI pytest command inherits parallelism, while -n 0 keeps one-core runs possible. Cap auto at four workers and respect affinity to avoid oversubscribing shared build hosts. No new credentials or permissions requested.

- 2026-10-26 — At high requested cadence, apply the capability-based ceiling to pending zero-delay continuous sends as well as extras, retaining only the newest pending continuous scene. Without this, 60 Hz continuous sends starve every legal extra send on the declared slower trace output. Render cadence remains selectable; the unchanged delay-shrink case remains intentionally bursty.
- 2026-10-26 — Compare phase-two idle colours with onset_delta_abs=1e9 on both revisions: sweep and pink noise have no sparse truth but do emit detector events by default. The comparison explicitly verifies zero emitted events, preserving both floating RGB traces and output bytes/timestamps rather than mislabelling noise events as absent.
- 2026-10-26 — Keep exact pins for changed detector strength/positions and publication accounting; preserve all existing ≤one-hop, survival and candidate-attribution contracts. Store six phase-two idle-colour hashes separately as immutable expectations.

- 2026-10-26 — Short-window candidates retain their containing hop's start coordinate; timestamped playback uses that hop's midpoint to bound within-hop truth uncertainty to ±5 ms. Pure long-window bass keeps its existing attack clock. The estimator uses no fixture truth; latency tests now assert both exact candidate deadlines and ±5 ms against click/impulse truth with the configured playback lead and light advance.
- 2026-10-26 — Mid/treble decisions use compressed short-window flux, but exported candidate strength_raw preserves the uncompressed band flux at that same candidate. Log differences saturate on successive tone-level increases (mid rho 0.8); preserving raw candidate magnitude restores the existing rho=1 contract without changing thresholds or picker decisions.
- 2026-10-26 — Keep SceneSchedule's strict due comparison. Advance the injected replay clock by the requested sleep directly: rounding the clock down could create a needless microsecond wake, while comparison tolerance could send a scene fractionally before its declared target.
- 2026-10-26 — Replace the architecture probe's random pre-warmup stream with a deterministic post-warmup impulse to verify a positive Beat-only publication; empty Beat contributions are deliberately absent under the new independent hop clocks.

- 2026-10-26 — The injected-clock early-output test stops after two cadence intervals, independent of the latest requested sleep. Exact deadlines can request a sub-frame sleep; using that duration as the entire test grace period cancelled the coroutine before its due send. Existing send/flush assertions remain unchanged.

- 2026-10-26 — Render continuous features at their requested cadence even when an extra send has just occurred; defer/coalesce the pending continuous send behind the capability ceiling. Enforce one extra per drain explicitly, including a deliberately slow-render test.
- 2026-10-26 — Use process-specific temporary method-config filenames with shared content hashes, avoiding simultaneous xdist config writes; include observer code in the replay cache fence.

Final LAT-01 headroom (one core, BLAS threads=1; CSV export excluded). Core
percentage includes analysis and output-loop execution. Backlog is the virtual
eligible publication backlog, not a claim about live OS wake jitter. Normal
publication evictions are unused continuous snapshots; all event drop counts
remain zero. Default cadence stays 30 Hz despite >11× CPU margin at 50 Hz.

Affinity: [7]

| Fixture | Route | Hz | DSP CPU ms/hop | Loop p95 / max ms | Core % | Margin | Virtual backlog | Pub / event drops |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| pink-noise | normal | 30 | 0.640 | 0.115 / 0.658 | 7.1 | 14.00× | 0 | 0 / 0 |
| pink-noise | normal | 50 | 0.634 | 0.128 / 1.053 | 7.2 | 13.81× | 0 | 0 / 0 |
| pink-noise | normal | 60 | 0.631 | 0.110 / 0.898 | 7.3 | 13.72× | 0 | 0 / 0 |
| pink-noise | timestamped | 30 | 0.640 | 0.424 / 1.244 | 7.7 | 12.99× | 0 | 0 / 0 |
| pink-noise | timestamped | 50 | 0.635 | 0.325 / 0.470 | 7.8 | 12.90× | 0 | 0 / 0 |
| pink-noise | timestamped | 60 | 0.644 | 0.265 / 1.100 | 7.9 | 12.59× | 0 | 0 / 0 |
| clicks-174 | normal | 30 | 0.742 | 0.120 / 0.953 | 8.0 | 12.54× | 0 | 24 / 0 |
| clicks-174 | normal | 50 | 0.716 | 0.132 / 1.391 | 8.0 | 12.56× | 0 | 24 / 0 |
| clicks-174 | normal | 60 | 0.704 | 0.115 / 1.208 | 7.9 | 12.64× | 0 | 24 / 0 |
| clicks-174 | timestamped | 30 | 0.707 | 0.361 / 1.610 | 8.1 | 12.28× | 0 | 0 / 0 |
| clicks-174 | timestamped | 50 | 0.753 | 0.231 / 1.034 | 8.8 | 11.42× | 0 | 0 / 0 |
| clicks-174 | timestamped | 60 | 0.710 | 0.239 / 1.420 | 8.4 | 11.86× | 0 | 0 / 0 |

- 2026-10-26 — Final evidence anchors implementation c5e6a7e; the final follow-up commit only records provenance, raw ledgers and transcripts. Force-track the two latency CSV artifacts because the repository generally ignores generated CSV files. Full runs use cold session caches and separate CPU affinity for the one/four-core measurements.


## CI-01 — native test coverage and worker isolation (2026-10-26)

- Diagnose runner failures from the GitHub job log. Run 40303173668 failed during
  Python 3.11 collection: workers shared the controller's application config and
  raced on `config.tmp` replacement. Give each worker a private config path;
  retain production Storage behavior and all assertions. No retry is added.
- Five fresh-environment Python 3.11.17 runs with four workers and no native library
  each passed (2114 passed, 93 skipped). The full-suite collection race did not
  reproduce locally. A targeted inherited-config regression fails before worker
  isolation and passes afterward; distinguish that evidence from reproducing the
  intermittent runner exception.
- Keep one standard-library-only compiler function in `scripts/build_native.py`,
  called by its command-line entry point and Hatch's build hook. The hook loads
  the script by source-root path so archived installer builds also work. CI builds
  the checkout library explicitly and checks the wheel contains a nonempty library.
  Compiler flags, sources, linking, and production behavior remain unchanged.
- Mark every cavacore-gated test `native` and centralize real library availability
  checks in one fixture. Local runs retain skips; `LAMPASTREAM_REQUIRE_NATIVE=1`
  makes unavailable libraries fail setup. Set it at CI test-job scope for every
  Python matrix entry. No runtime dependency is added.
- Use the documented `pytest -v -m native` command for native coverage visibility.
  Local validation ran all 88 native cases, including all 12 backend-context parity
  cases. Removing the library yields 88 native skips without the flag and 88 setup
  failures with it; restoring it yields 88 passes in both modes. The full required
  run passed with 2203 passed and 5 unrelated skips.

## ACCENT-01 — visible universal event accents (2026-10-26)

- Supersede the 2026-10-25 decision that default spectrum_rgb onsets remain
  invisible until Styles. Default every existing/new Effect to lift at 0.35,
  weights bass/mid/treble 1/0.6/0.4. Missing persisted fields receive dataclass
  defaults, with schema support for the weight dictionary. Export/import carries
  every field; no migration and no new runtime dependencies.
- Apply once after LayerMixer and before output precision on both routes.
  EVENT-01 owns hold/release/retrigger; no raw flags or tick decay enter accents.
  The research's 20–30 ms cone integration and 50–100 ms maximum perceived flash
  brightness motivate retaining the capability minimum hold (two output frames;
  80 ms on the slow reference). Audio-leading light lateness becomes detectable
  around 15–45 ms; preserve LAT-01 scheduling rather than adding another clock.
- Normalize the envelope's embedded strength before applying strength^gamma and
  newest-event confidence; max-merge weighted band envelopes. Combined events
  have only an all envelope, so use unit broadband weight. Zero explicit band
  weights remain zero. Sort spatial positions lexicographically, choose every
  other mid position starting at zero, and resolve furthest-distance ties by
  that order. The explicit none effect remains dark.
- Interpolate peak intensity in linear light and scale the encoded RGB direction
  together. This preserves HSV hue/saturation exactly instead of introducing
  angle shifts from separate nonlinear component interpolation. Pop increases
  saturation; palette_step advances a cyclic configured-palette coordinate per
  counted event, with the named gradient starter for an unpaletted effect.
- Retain the double response of flashes/pulses/splotches/fireworks. Measured
  exception to the proposed intensity rule: flashes did not clip, but its
  near-white peak left only 3.90 additional codes on the slow room, below the
  required eight. Scale its internal envelope to 0.85 when accents are enabled
  to reserve lift headroom; off retains original intensity. All 52 effect ×
  route × depth cases then pass, with zero clipped components. No other internal
  intensity changed. Deprecate the legacy flash control without dropping it.
- Keep phase-4 evidence in traces-phase4, alongside the earlier sets. Pin complete
  LAT-01 accent-off trace bytes for ten fixtures × two routes against 6986d9a;
  also audit retained render columns. Schema and default-export additions change
  configuration bytes only, so regenerate the reproducible default fixture.
- Extend the existing preview socket payload and TypeScript contracts; share its
  diagnostics through status so Light timing does not create a second socket.
  Preserve latest diagnostic fields when periodic status metadata arrives. Build
  and commit the frontend bundle with the pinned Node 22.22.2.

- Final GitHub verification exposed an existing xdist WAV-fixture race in job
  121577855373 (Python 3.11): another worker deleted the shared
  tests/tmp_accept/sine_440_harness_test.wav before metadata hashing. Give each
  worker/session a unique owned directory beneath the same ignored repository
  parent, preserving Windows ffmpeg visibility and deleting only its own files.
  Production behavior and every assertion remain unchanged; no retry is added.


## ACCENT-01 Send-back 1 — event-based preview indicators (2026-10-27)

- The 19/19 event-path and raw-snapshot grep contracts remain. Send-back 2
  supersedes render-time preview publication and the earlier acceptance of
  timestamped preview lead; all indicators now follow the audible snapshot.

## ACCENT-01 Send-back 2 — one audible preview clock (2026-10-27)

- Timestamped preview envelopes trigger at each event's play_monotonic and are
  evaluated at server now, without onset_lead_s or the lamp hop-midpoint advance.
  The ingress playback lead is already represented by play_monotonic; it is not
  added again. Changing lamp advance from 20 to 100 ms leaves all 19 preview
  activation times identical. Compatibility flags hold for 50 ms from playback.
- Normal preview freezes the envelope/accent view belonging to the scene actually
  sent after the delay buffer. The compatibility hold begins on that send, not
  on render or analysis receipt. A 200 ms buffer therefore moves every preview
  quantity together with the shown frame.
- Capture exact post-boundary channel colours from send(), without re-sampling
  the output precision guard. Timestamped preview retains these immutable sent
  frames on the playback timeline: map their lamp-event anchor to the event's
  play_monotonic. This removes lamp advance from dot colours and dot outlines as
  well as the room outline. The renderer and all lamp scheduling stay unchanged.
- Publish one atomic snapshot per websocket frame, including colours, band/all
  envelopes, accent/lifts, compatibility flags, event counts and audible_monotonic.
  On normal output the timestamp is the shown frame's send time; on timestamped
  output it is the evaluation time (server now). Preview getters advance only
  the preview timeline, never renderers, event queues or output state.
- Browser scheduling is deferred. The residual is the websocket interval plus
  browser rendering, roughly 50–80 ms. Dots and outlines share it because they
  come from the same snapshot. Keep the timestamp for later browser scheduling.

## PREVIEW-01

- 2026-10-27 — Start from pulled 8f5385b; preserve the owner's untracked design image. Preview-only hooks observe existing event/render/send boundaries; no lamp scheduling, renderer, envelope, accent, output boundary or HueDriver changes.
- 2026-10-27 — Publish timestamped events at pre-render time with their canonical playback timestamps and post-accent scene samples; publish normal events with exact carrying-send colours and send-clock anchors. Never sample the stateful output precision guard for a preview.
- 2026-10-27 — Coalesce already available events within 5 ms without a timer that would delay normal-route publication. Preserve each event's own timestamp and channel snapshot inside the transport batch. Bound queue/history growth and isolate failing subscribers from output.
- 2026-10-27 — Keep the 50 ms continuous producer; push events and answer clock pings in independent socket tasks. Use midpoint RTT and a seven-sample median for server-minus-browser clock offset. Unknown clock falls back to immediate activation and an explicit unsynchronised indicator.
- 2026-10-27 — Browser requestAnimationFrame owns event hold/release and colour precedence during hold. Periodic frames cannot retrigger the event path. Reset/reconnect discards queued event state; no runtime or frontend dependencies added.
- 2026-10-27 — Report controlled software activation residuals separately from socket delivery lead and earlier poll latency; no physical lamp/audio or live-network measurements are inferred. No deployment or owner-device contact.
