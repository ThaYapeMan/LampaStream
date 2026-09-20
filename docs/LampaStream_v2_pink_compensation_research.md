# HueSync — V2 spectrum engine: research, analysis and the pink-noise fix

Date: 2026-09-18
Deliverable: `v2_bars_pink.py` (self-verified reference implementation)

## The observed problem

On the live system, with an AirPlay coupling on the canonical pipeline and the V2
engine, the `spectrum_rgb` output turns almost entirely red the moment a beat becomes
dominant: bass bars high, mid near zero, treble zero. Beat detection on the same
session was judged *better* than the cava path. Both observations are explained by
one design gap, below.

## How V2 compares to what it claims to be modelled on

V2's docstring says it follows WLED AudioReactive ("WLED-style adaptive reference",
"matches hardware analysers and WLED"). WLED's actual post-processing chain
(`usermods/audioreactive/audio_reactive.cpp`, `postProcessFFTResults`) is:

1. `fftCalc[i] *= fftResultPink[i]` — **per-band pink-noise compensation**, a static
   multiplier table `{1.70, 1.71, 1.73, 1.78, 1.68, 1.56, 1.55, 1.63, 1.79, 1.62, 1.80,
   2.06, 2.47, 3.35, 6.83, 9.55}` for its 16 bands
2. global gain / AGC (`multAgc`)
3. per-band rise-fast / fall-slow smoothing (`fftAvg[i]`)
4. optional logarithmic output scaling (`FFTScalingMode 1`)

V2 implements 2 and 3 faithfully and omits 1 and 4. Step 1 is the one that matters
for the red problem.

This is not an obscure detail. The MoonModules team — who maintain WLED AudioReactive
— reviewed a Music Assistant integration and noted that "WLED's own onboard analysis
additionally applies a 'pink noise' per-band compensation (fftResultPink) before any
curve, which was missing entirely" (music-assistant/server PR #5537). The same
omission, found the same way: by comparing against real hardware. They also state
the acceptance test: *"Play a pink noise audio sample → all GEQ bars should be on
similar level (some jitter expected)."*

## Why the omission produces "all red"

V2 normalises every bar against **one** global peak EMA (`self._v2_peak_ema`, a
scalar; `peak = max(bar_mags)`). Music has a roughly 1/f magnitude tilt — the bass
bins carry far more raw magnitude than the treble bins. So the single reference is
always set by the bass bar; bass normalises to ~1.0 and everything else is divided by
a bass-sized number. When the beat gets stronger the reference rises further and mid
and treble sink further. Measured on synthetic pink noise through V2's exact bin→bar
mapping: **19.1 dB spread** between the loudest and quietest bar, on input that should
read flat.

A global AGC is not wrong — WLED keeps one too, deliberately, so that bass-heavy music
still *reads* bass-heavy. What is missing is the static tilt correction in front of it.

Why beat detection is unaffected: `BeatDetector` is a separate processor on the raw
STFT and does not pass through this normalisation at all. The canonical pipeline's
100 Hz / 10 ms hop is also finer in time than cava's 30 Hz bars. Better onsets and
worse colours on the same session are two independent facts, both expected.

## Why WLED's table cannot simply be copied

`fftResultPink` is hand-tuned for one fixed layout: 16 bands, ~60 Hz–10 kHz, a
specific FFT size and a specific bin-to-band map. V2 has 10–60 bars over a user-set
`lower_cutoff_freq`–`higher_cutoff_freq`. A 16-entry table has no meaning for a
34-bar 50–12000 Hz analyser.

There is also a second-order effect a formula would miss: V2 takes `np.max` within
each bar. A treble bar spanning 76 bins takes the max of 76 noisy values; a bass bar
spanning 1 bin takes the max of 1. The max of many samples is biased upward, so wide
bars are lifted by the statistic itself, partially offsetting the 1/f tilt. Any
correct table has to fold that in, and it depends on the layout.

## The fix: derive the table for the actual layout

`derive_pink_compensation(n_bars, lower_hz, upper_hz)` pushes synthetic pink noise
(magnitude ∝ 1/√f, Rayleigh-scattered per bin, as a windowed FFT of noise really is)
through V2's *identical* bin→bar mapping including `np.max`, tracks the same
peak-hold falloff the engine displays, and inverts the steady-state per-bar
response. Normalised so the lowest bar has gain 1.0 (compensation only lifts, never
attenuates the bass), clipped at 12× (WLED's steepest hand-tuned entry is 9.55×),
deterministic (fixed seed), computed once at engine construction.

A detail that mattered and was found only by measuring: deriving on the per-frame
**mean** left 5–6 dB of residual spread. A 1-bin bar has far more frame-to-frame
scatter than a 76-bin bar, so equal means still give an unequal peak-hold. Deriving
on the **peak-held** statistic — the thing actually on screen — is what makes the
bars come out level.

The chain becomes, with exactly one insertion:

```
1. bin→bar np.max, squelch gate                 (unchanged)
2. × per-bar pink compensation                  (NEW)
3. global peak EMA, fast attack / slow release  (unchanged)
4. per-bar falloff                              (unchanged)
```

Deliberately unchanged: `np.max` per bar (V2's character), the global AGC (cross-band
dynamics), the 0..1 linear output (what effects and the Energy Profile assume). WLED's
log output scaling (step 4 in their chain) is a separate decision with different
downstream semantics and is not applied.

## Verification — measured, on the person's own live layout (34 bars, 50–12000 Hz)

```
OK  pink-noise spread: 19.1 dB before → 1.1 dB after
    compensation table: first=1.00 mid=3.23 last=9.13
    bass tone   → bar0..2 max 1.00, upper half max 0.000
    treble tone → last4 max 1.00, lower half max 0.000
```

- **Pink noise flat to 1.1 dB** (time-averaged over 3 s), from 19.1 dB — the MoonModules
  acceptance criterion, met. Single-frame values still jitter ±2–3 dB; that is random
  noise scatter, not tilt, and is the "some jitter expected" in their own wording.
- **A pure 80 Hz tone** still reads as bass at full scale with the upper half at exactly
  zero — the compensation does not invent treble.
- **A pure 8 kHz tone** reaches full scale in the top bars with the lower half at zero.
- **The derived top-band gain is 9.13×.** WLED's hand-tuned top entry is 9.55×. An
  analytically derived value landing within ~5 % of what the WLED team tuned by
  measurement and ear is a strong independent check that the derivation is right.

What this does *not* prove: how it feels on real music in the room. Synthetic tones
and noise are the right way to prove the mechanism; the person's eyes on the LXC are
the only way to prove the result. The expectation to check: mid and treble visibly
present during a dominant beat, and the AirPlay/V2 session no longer looking
categorically worse than the LMS/cava one.

## One unrelated thing found in the same code, worth removing

`V2SpectrumEngine.feed()` still carries a `# TEMPORARY DIAGNOSTIC` block —
"Remove once mushy-output defect is confirmed fixed on LXC" — that logs at INFO level
every 50 frames, i.e. roughly twice a second at the 100 Hz hop. These are the `[diag]`
lines seen filling `journalctl` earlier. It should go, or drop to DEBUG.

## Follow-up, separate task, not this one

The cava path additionally runs `BandNormaliser` (dynamic per-band AGC against each
band's own rolling average) on its bars; the canonical path runs no equivalent. The
static pink table fixes the *systematic* tilt; `BandNormaliser` adapts to the
*specific* track and room. Routing the canonical path's bars through the existing
`BandNormaliser` as well would give V2 both, and is probably the single largest
remaining difference between the two paths — but it is pipeline wiring, not the
engine, and should be tested on its own after this change has been judged.

## References

- WLED `audio_reactive.cpp` (fftResultPink, postProcessFFTResults):
  https://github.com/wled/WLED/blob/main/usermods/audioreactive/audio_reactive.cpp
- MoonModules on the missing pink compensation and the pink-noise test:
  https://github.com/music-assistant/server/pull/5537 ,
  https://github.com/MoonModules/WLED-AudioReactive-Usermod/issues/7
