# GRID-01 UDKM findings

## Owner-verified reference — 2026-11-12

The owner listened at the disputed spots. Those verdicts supersede the earlier
unverified absence labels below; they are not labels generated from the analyser.

| Track | Reviewed spot | Owner verdict (2026-11-12) | Reference consequence |
| --- | --- | --- | --- |
| UDKM | 0:10–0:28 | Bass drum present, double hit | Presence is 1 throughout the owner-authorized 0.4–28.5 s range |
| UDKM | 0:39–0:52 | Bass drum present, single/double | Presence is 1; the former short stops are removed |
| UDKM | 7:58–8:06 | Bass drum continues to the end | Presence is 1 from the old 480.9 s row through the end |
| Mau P | 1:25.3 and 2:29.5 | Soft bass drum present | Rows 182 and 319 become 1 |
| Mau P | 3:08.9, 3:09.4, 3:09.9, 3:14.5, 6:10.8, 6:17.4 | Softer beat: flash with less intensity | Rows 403, 404, 405, 415, 791, 805 become 2 (reduced) |
| Lou Rawls | 1:32.5 and 1:48.1 | Band continues in time with a solid bass drum | Misplaced tracker beats, not missing beats; re-place locally without changing the count |

UDKM keeps fixed 129.985 BPM and 1,053 rows. Current reference phase is the
first sufficient layered transient, 0.373859195291779 s (−16.840805 ms from
the archived body phase). The median uses 910 full-level body events at 60–480
s, the same ±70 ms / 50% sufficiency rule, and the earliest qualifying peak.
The original file is archived as `beats-body-phase.csv`; only the current
`beats.csv` carries the owner-corrected labels.

Owner-authorized presence ranges are 0.4–28.5 s, 39–52 s and 480.9 s to the
end, mapped to existing rows before re-phasing. They remove both previously
reported short stops. The resulting reference has 1,052 present rows and one
initial absent row. The phase is derived from the specified low-band events;
no presence label is inferred from output flags.

### Known gap: soft bass drums in quiet intros

The intro is about 13 dB below the body. Against the corrected reference, the
current analyser misses 40 of the 129 present rows before 60 s; it produces no
false positives there. Both channels' on-beat and off-beat energies and offsets
are recorded for every miss in the table below and in the 5d report's evidence CSV. The lamps
stay dark on these missed soft events: the conservative error is accepted for
this ticket, not erased from the reference and not corrected by threshold tuning.
This is the next intro-behaviour bench target for BEAT-02.

The body (t ≥60 s) has 923 reference rows and seven misses, all in the final
passage: agreement 99.241603%, exceeding the 98% requirement. All 1,040 timing
rows through 480 s are within ±10 ms (maximum 3.206041 ms). Neither the
nearest-sufficient picker nor its strength/hysteresis thresholds is retuned.

### Intro miss evidence (both channels)

On-beat energy uses the current grid time; off-beat energy uses that time plus
half the fitted period. Each channel uses the same nearest sufficient low-band
attack picker (±70 ms, at least 50% of the window maximum). Energies are linear
attack-envelope values, without normalization to the louder body. Row indices
are zero based. All 40 rows below have reference 1 and output false.

| Row | Reference s | Grid s | Left on | Left off | Right on | Right off |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.835451 | 0.838656 | 0.01286166 | 0.009886076 | 0.01413158 | 0.01086665 |
| 2 | 1.297043 | 1.300246 | 0.009550229 | 0.008341378 | 0.01053137 | 0.01689926 |
| 3 | 1.758634 | 1.761837 | 0.01759041 | 0.00872542 | 0.01873628 | 0.00950839 |
| 4 | 2.220226 | 2.223427 | 0.006828073 | 0.008288652 | 0.00844589 | 0.009224666 |
| 5 | 2.681818 | 2.685018 | 0.004978246 | 0.004909451 | 0.005890721 | 0.004904579 |
| 6 | 3.143410 | 3.146608 | 0.0109224 | 0.01122417 | 0.01216155 | 0.01192643 |
| 7 | 3.605001 | 3.608199 | 0.01251511 | 0.03075284 | 0.01341694 | 0.03415795 |
| 8 | 4.066593 | 4.069789 | 0.02033091 | 0.0217086 | 0.02188395 | 0.02427408 |
| 9 | 4.528185 | 4.531380 | 0.007953297 | 0.008566405 | 0.008592745 | 0.00997241 |
| 10 | 4.989776 | 4.992970 | 0.005824194 | 0.01039633 | 0.006154178 | 0.0114166 |
| 11 | 5.451368 | 5.454561 | 0.008144572 | 0.01023477 | 0.008739954 | 0.01144599 |
| 12 | 5.912960 | 5.916151 | 0.01127333 | 0.02285752 | 0.01209599 | 0.02486482 |
| 13 | 6.374552 | 6.377742 | 0.009284841 | 0.01200016 | 0.01099692 | 0.01321596 |
| 14 | 6.836143 | 6.839332 | 0.004676351 | 0.007628581 | 0.005539425 | 0.00811859 |
| 15 | 7.297735 | 7.300923 | 0.01153191 | 0.007392194 | 0.01239923 | 0.007988485 |
| 16 | 7.759327 | 7.762513 | 0.008155052 | 0.01043178 | 0.008815565 | 0.01069756 |
| 17 | 8.220918 | 8.224104 | 0.01001574 | 0.01249979 | 0.007544225 | 0.01360435 |
| 18 | 8.682510 | 8.685694 | 0.01184754 | 0.00993816 | 0.01426049 | 0.01097081 |
| 19 | 9.144102 | 9.147285 | 0.004644714 | 0.003530579 | 0.004987322 | 0.002871767 |
| 20 | 9.605694 | 9.608875 | 0.01588103 | 0.007085741 | 0.0176068 | 0.007549945 |
| 22 | 10.528877 | 10.532056 | 0.01095572 | 0.001665896 | 0.01432302 | 0.003141156 |
| 23 | 10.990469 | 10.993647 | 0.03764758 | 0.02339983 | 0.03271372 | 0.02498183 |
| 24 | 11.452061 | 11.455237 | 0.01551475 | 0.04609566 | 0.0152599 | 0.02290371 |
| 25 | 11.913652 | 11.916828 | 0.05289537 | 0.03131599 | 0.04815141 | 0.03701042 |
| 26 | 12.375244 | 12.378418 | 0.01278374 | 0.001587659 | 0.01640959 | 0.002217676 |
| 28 | 13.298427 | 13.301599 | 0.0356458 | 0.06174005 | 0.0211496 | 0.0269209 |
| 29 | 13.760019 | 13.763190 | 0.07587518 | 0.02250408 | 0.05475534 | 0.01429745 |
| 30 | 14.221611 | 14.224780 | 0.01249079 | 0.002316707 | 0.01632768 | 0.00185394 |
| 31 | 14.683203 | 14.686371 | 0.05768273 | 0.0368594 | 0.05539412 | 0.04276081 |
| 32 | 15.144794 | 15.147961 | 0.01050381 | 0.0365492 | 0.016606 | 0.05332421 |
| 33 | 15.606386 | 15.609552 | 0.03437528 | 0.0419062 | 0.02664945 | 0.0464406 |
| 34 | 16.067978 | 16.071142 | 0.01462452 | 0.02915434 | 0.01905761 | 0.04207524 |
| 35 | 16.529569 | 16.532733 | 0.02372502 | 0.0861716 | 0.05585094 | 0.09305425 |
| 38 | 17.914345 | 17.917504 | 0.01205356 | 0.002681755 | 0.01707501 | 0.003364691 |
| 39 | 18.375936 | 18.379095 | 0.0281245 | 0.03086356 | 0.02141749 | 0.03869095 |
| 40 | 18.837528 | 18.840685 | 0.06309461 | 0.04625661 | 0.06478047 | 0.01610201 |
| 41 | 19.299120 | 19.302276 | 0.03330243 | 0.02758915 | 0.03028414 | 0.03115169 |
| 42 | 19.760712 | 19.763866 | 0.01390137 | 0.0301837 | 0.01943065 | 0.03838807 |
| 46 | 21.607078 | 21.610228 | 0.01581611 | 0.002153418 | 0.01449292 | 0.003042256 |
| 106 | 49.302582 | 49.305659 | 0.01037822 | 0.002115408 | 0.01818925 | 0.002719496 |

## Historical 2026-11-11 analysis (presence claims superseded)

Owner analysis, 2026-11-11: Armand Van Helden — “U Don't Know Me feat. Duane
Harden (Original Mix)”, ALAC, 44.1 kHz, 8:06; published tempo 130 BPM.

| Evidence | Finding |
|---|---|
| Rigid tempo | 129.985 BPM throughout; fit on 90–300 s puts bass drums within ±8 ms from 60 s to end; reported MAD 9 ms |
| Intro | First minute is 10–13 dB quieter; no bass drum before 28 s; soft bass drum from about 28.5 s; full level from about 60 s |
| Bass drum absences | 0.4–28.5 s, 41.9–43.3 s, 47.0–52.1 s, 480.9 s–end |
| Baseline at d62bbd6 | 130.731 BPM, 1046 beats, confidence 0.93 |
| Beatwise gating | Soft bass drums cross the file-wide threshold at random |
| Intro refinement | Nearest low-band attacks can be bass notes; local residual standard deviation 110 ms versus 4–6 ms in body |
| Discarded fit | Both regularity branches return observed positions, so the computed rigid lattice is lost |
| Tempo label | Median attack intervals are hop-quantised; fitted period must define the tempo |
| Tracker slip | Beat insertion/deletion around 340–370 s; fit residual jumps −204 → +170 ms |

Owner's baseline 30–90 s flag pattern:

```text
............K.....K.KK....KKK..K..KKK.....KKK.KK..KKKKKKKKKKKKK.K.K.KKK.K.K...KKK.K.KKKK…
```

The private fixture is outside the checkout. That original reference is now archived in
`tests/fixtures/ab-references/avh-udkm/beats-body-phase.csv`; the current
`beats.csv` uses the owner-reviewed phase and labels above.
The implementation measurements, tuning results and remaining acceptance failures
are recorded in the GRID-01 send-back 4 report, separately from these owner facts.
