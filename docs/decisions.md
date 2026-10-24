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
