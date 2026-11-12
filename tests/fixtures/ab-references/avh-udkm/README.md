# Armand Van Helden — U Don't Know Me (Original Mix)

The 1,053-row reference is owner-verified at disputed spots on 2026-11-12.
Columns are zero-based `beat`, content `time_s`, and binary `kick` (bass drum
presence). No private audio is committed.

`beats.csv` uses the **first** of the layered bass drum hits, rather than the
later body. At fixed 129.985 BPM, period = 60/129.985 seconds, the phase is
0.373859195291779 s. It is the median of 910 earliest sufficient low-band
attacks over the full-level body from 60 to 480 s, minus each row's beat index
× period. Candidates are local peaks within ±70 ms of the old body reference,
at least 50% of the window maximum. Both canonical channels contribute through
the existing max envelope. The shift from the old phase 0.3907 s is −16.840805
ms. This reference definition targets the first transient; it does not reuse
the analyser's returned grid positions.

`beats-body-phase.csv` preserves the previous file byte for byte. It defines
the later body phase and retains the historical labels for provenance only;
its old presence/absence labels are superseded by the owner's listening.

Owner time ranges are mapped to the old body-phase rows before retiming, so
beat identities do not change with the phase convention. Presence is set to 1
for 0.4–28.5 s, 39–52 s, and from 480.9 s through the end. The former stops
at 41.9–43.3 s and 47.0–52.1 s are removed. All other labels stay unchanged.
Totals: 1,052 present and one absent (the initial extrapolated row).

Timing acceptance covers every reference beat through 480 s within ±10 ms.
Flag agreement is ≥98% on t ≥60 s. Before 60 s, missed soft bass drums are
reported with both channels' on/off-beat evidence, rather than changing labels
or tuning thresholds. See [the owner verdicts](../README.md) and
[UDKM findings](../../../../docs/research/grid01-udkm-findings.md).

Private ALAC audio is enabled with `LAMPASTREAM_GRID_FIXTURE_UDKM`; it remains
outside the checkout and CI. Lou Rawls uses `LAMPASTREAM_GRID_FIXTURE_LOU`;
Mau P uses `LAMPASTREAM_GRID_FIXTURE`. Acquisition tests use local loopback
fixtures only, never an owner LMS.
