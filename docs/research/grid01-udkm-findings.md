# GRID-01 UDKM findings

Owner analysis, 2026-11-11: Armand Van Helden — “U Don't Know Me feat. Duane
Harden (Original Mix)”, ALAC, 44.1 kHz, 8:06; published tempo 130 BPM.

| Evidence | Finding |
|---|---|
| Rigid tempo | 129.985 BPM throughout; fit on 90–300 s puts kicks within ±8 ms from 60 s to end; reported MAD 9 ms |
| Intro | First minute is 10–13 dB quieter; no kick before 28 s; soft kick from about 28.5 s; full level from about 60 s |
| Kickless stretches | 0.4–28.5 s, 41.9–43.3 s, 47.0–52.1 s, 480.9 s–end |
| Baseline at d62bbd6 | 130.731 BPM, 1046 beats, confidence 0.93 |
| Beatwise gating | Soft kicks cross the file-wide threshold at random |
| Intro refinement | Nearest low-band attacks can be bass notes; local residual standard deviation 110 ms versus 4–6 ms in body |
| Discarded fit | Both regularity branches return observed positions, so the computed rigid lattice is lost |
| Tempo label | Median attack intervals are hop-quantised; fitted period must define the tempo |
| Tracker slip | Beat insertion/deletion around 340–370 s; fit residual jumps −204 → +170 ms |

Owner's baseline 30–90 s flag pattern:

```text
............K.....K.KK....KKK..K..KKK.....KKK.KK..KKKKKKKKKKKKK.K.K.KKK.K.K...KKK.K.KKKK…
```

The private fixture is outside the checkout. The reference timestamps and flags
are committed unchanged in `tests/fixtures/ab-references/avh-udkm/beats.csv`.
The implementation measurements, tuning results and remaining acceptance failures
are recorded in the GRID-01 send-back 4 report, separately from these owner facts.
