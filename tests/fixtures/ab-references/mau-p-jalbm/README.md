# Mau P — Just A Little Bit More (Extended)

`beats-librosa.csv` preserves the owner's original 814-row tracker CSV byte for
byte, including its hop quantisation and irregular tail. `summary.json` is the
unchanged original summary (steady fitted tempo 127.9984 BPM).

At the owner's explicit request during GRID-01 send-back 4, `beats.csv` now uses
the same `beat,time_s,kick` columns as UDKM and a rigid fitted period:
127.9980245095687 BPM, period 0.4687572345736858 s, first nonnegative lattice
point 0.01874461922111594 s. The phase is the median bass drum attack phase; there are
814 nonnegative beats before the 381.221995 s end. The first 797 form the timing
acceptance window. The first actual bass drum is the next lattice point, 0.487502 s.

On 2026-11-12 the owner listened to every disputed spot. `kick` now means:

- 0: no bass drum (155 rows).
- 1: full bass drum (653 rows).
- 2: reduced accent (six rows), to flash with less intensity.

Rows 182 and 319 are owner-confirmed soft bass drums and become 1. Rows 403,
404, 405, 415, 791 and 805 become 2. Of those six, two were previously 1 and
four were 0, so the corrected totals are 653/155/6 = 814, as clarified by the
owner. Times and row order are unchanged. The historical labels were initially
preserved from an independent 40–150 Hz RMS-rise classification; disputed spots
are now governed by owner listening, not by regenerating analyser labels.

Binary acceptance requires all reference-1 rows on and all reference-0 rows off.
Reference-2 rows are excluded from both counts until BEAT-02 implements reduced
intensity; their current analyser output is reported without scoring it. They
also do not define a binary break-count expectation. The required timing window
remains the first 797 rows within ±10 ms of the rigid reference.

Private audio stays outside the checkout. Set `LAMPASTREAM_GRID_FIXTURE` to the
FLAC file to enable acceptance and loopback fake-LMS acquisition/cache tests.
