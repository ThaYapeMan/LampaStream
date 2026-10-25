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
