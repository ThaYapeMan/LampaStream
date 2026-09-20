# HueSync colour rework v2 — lessons from LedFx

Supersedes the earlier `HueSync_colour_modes_brief_for_claude_code.md` on two
important points. That brief was right about relative energy, spectral centroid
and onset detection, but it missed the two things that actually explain the
current behaviour.

## Symptom

With `spectrum_rgb` (bass→R, mid→G, treble→B), the output is overwhelmingly
**yellow**, both before and after adding per-band EMA normalisation.

Yellow = red + green with little blue = bass and mid present, treble absent.

## Root cause 1: the frequency range is wrong

[LedFx](https://github.com/LedFx/LedFx) is the mature reference implementation
for audio-reactive lighting. Its
[melbank documentation](https://docs.ledfx.app/en/latest/developer/melbanks.html)
is explicit about the constants it uses and why:

```
FFT_SIZE  = 4096
MIC_RATE  = 30000     # deliberately NOT 44100
MAX_FREQ  = 15000
MIN_FREQ  = 20
MEL_MAX_FREQS = [350, 2000, 15000]
```

On the 30000 Hz choice, the docs say it is done to *increase frequency
resolution for bass (where Hz differences are smaller)* and to *focus
processing power on the audible range humans care about*.

The key point: **they cap at 15 kHz and treat everything above that as not
worth spending resolution on.**

cava, by default, spreads its bars over a much wider range. Music has almost no
energy above ~10 kHz. So HueSync's "treble" band — the top half of the frame —
sits near zero permanently, blue never lights up, and everything is yellow.

**Fix:** set cava's cutoff frequencies explicitly in the generated config:

```ini
[general]
bars = 24
lower_cutoff_freq = 50
higher_cutoff_freq = 12000
```

Verify the exact option names against the installed cava version
(`man cava` or `/etc/cava/config`) before relying on them. This change alone
should make blue appear.

## Root cause 2: three bands → RGB is not how this is done

LedFx does not map frequency bands to colour channels at all. It uses
**gradients**: a curated colour palette, with audio energy indexing into and
modulating that gradient. The colours look good because they were *chosen*,
not computed from spectral content.

Mapping bands to R/G/B produces whatever colour the spectrum happens to imply,
which for most music is a muddy region of colour space. There is no palette
constraining it to combinations that look pleasant.

**Fix:** add a gradient-based mode. Define a small set of palettes (e.g.
warm sunset, ocean, neon, monochrome), pick a position in the gradient from a
single audio feature, and modulate brightness from overall energy. Concretely:

- **position in gradient** ← spectral centroid (bass-heavy = one end,
  bright/airy = the other), or dominant band index
- **brightness** ← overall energy, after normalisation
- **palette** ← a per-profile setting

This is a bigger change than tweaking the band boundaries, but it is what makes
the difference between "technically reactive" and "actually looks good".

## Also worth adopting from LedFx

### Mel-scale band boundaries, not linear fractions

`_band_average()` currently treats positions as linear fractions of the frame.
The mel scale uses narrow bands at low frequencies (where hearing is more
sensitive) and wide bands at high frequencies. LedFx's default bin table shows
what this means in practice: bins 0-2 each cover roughly 50-70 Hz, while the
top bin spans about 3300 Hz.

The documented mapping (24 bins, 20 Hz - 15 kHz) is roughly:

| Bins  | Range          | Content                        |
| ----- | -------------- | ------------------------------ |
| 0-4   | 20-389 Hz      | sub-bass, bass, kick           |
| 5-9   | 389-1179 Hz    | lower mid to upper mid         |
| 10-14 | 1179-2976 Hz   | presence, sibilance            |
| 15-23 | 2976-15000 Hz  | high frequency through air     |

Note how the bass occupies five bins out of 24 — a fifth of the frame, not the
15% the current code assumes.

cava is already log-spaced, which approximates this, but the band boundaries in
`_band_average()` must be chosen with that in mind rather than as even splits.

### Peak isolation

LedFx applies a `peak_isolation` factor (default 0.4) — a non-linear power
scaling that makes bright regions brighter and dim regions dimmer, described in
the docs as creating more "punchy" visuals. A single exponent applied to
normalised band values, exposed as a profile setting.

### Automatic gain control

LedFx runs `mel_gain` (AGC) plus temporal smoothing on the melbank. The
BandNormaliser added in step 1 is the same idea; worth checking the interaction
with peak isolation once both exist (normalise first, then apply the exponent).

## Suggested order

1. **Set cava's cutoff frequencies.** Smallest change, addresses the yellow
   directly. Test by ear before anything else.
2. **Rework the band boundaries** in `_band_average()` to mel-like proportions
   (bass roughly the lower fifth, not the lower 15%).
3. **Add peak isolation** as a profile setting.
4. **Add a gradient mode** with two or three palettes. This is the real fix for
   "the colours don't look good", as opposed to "the colours don't respond".

Steps 1-3 are small. Step 4 is the substantial one and is best done as its own
piece of work once 1-3 confirm the analysis pipeline is behaving.

## Sources

- LedFx melbank architecture (frequency constants, bin table, peak isolation,
  AGC): https://docs.ledfx.app/en/latest/developer/melbanks.html
- LedFx gradient extraction:
  https://docs.ledfx.app/en/latest/developer/gradient_extraction.html
- LedFx project: https://github.com/LedFx/LedFx (GPL-3, so read it for ideas
  and approach — do not copy code into this MIT-licensed project)
