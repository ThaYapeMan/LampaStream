# Mau P — Just A Little Bit More (Extended)

`beats-librosa.csv` preserves the owner's original 814-row tracker CSV byte for
byte, including its hop quantisation and irregular tail. `summary.json` is the
unchanged original summary (steady fitted tempo 127.9984 BPM).

At the owner's explicit request during GRID-01 send-back 4, `beats.csv` now uses
the same `beat,time_s,kick` columns as UDKM and a rigid fitted period:
127.9980245095687 BPM, period 0.4687572345736858 s, first nonnegative lattice
point 0.01874461922111594 s. The phase is the median kick-attack phase; there are
814 nonnegative beats before the 381.221995 s end. The first 797 form the timing
acceptance window. The first actual kick is the next lattice point, 0.487502 s.

The 653 kick / 161 kickless labels preserve the previous benchmark's independent
classification of the original timestamps: 40–150 Hz positive 5-ms RMS rise,
±70 ms peak window, threshold 0.06046597196118645. Labels retain beat order,
with an initial kickless extrapolated lattice point and the final kickless
tracker-only row omitted. This aligns the original first kick to the new second
row, without inventing an attack at track zero. These are preserved reference
labels, not labels regenerated from the new detector's output.

Private audio stays outside the checkout. Set `LAMPASTREAM_GRID_FIXTURE` to the
FLAC file to enable acceptance and loopback fake-LMS acquisition/cache tests.
