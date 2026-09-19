# HueSync: better colour modes — brief for Claude Code

## Context

HueSync currently maps three fixed frequency bands to R/G/B (`spectrum_rgb` in
`sync_engine.py`). In practice the colours don't match what you hear: bass
dominates energetically in almost all music, so the output is nearly always
red-heavy with little variation. This brief describes three improvements,
ordered by value-for-effort.

**Constraints to respect:**

- Input is cava's raw output: `profile.bars` single bytes (0-255), one frame,
  read from a FIFO. See `FifoReader` in `sync_engine.py`.
- cava's bars are spaced **logarithmically** across frequency, but the current
  `_band_average()` treats positions as linear fractions of the frame. Any new
  band boundaries need to account for this.
- Runs on a lightweight LXC (2 vCPU). Realtime only — no librosa, no HPSS, no
  key detection. Those are ahead-of-time techniques and don't belong here.
- The sender runs at a fixed 30 Hz (`SEND_INTERVAL_S`). Per-frame state must
  survive across calls, so anything with history needs to live on the engine
  or the mode object, not in a local variable.
- Existing modes (`spectrum_rgb`, `bass_brightness`, `mono_pulse`) must keep
  working. Add new modes, don't replace.

---

## 1. Relative energy instead of absolute (biggest win, least effort)

**Problem:** the current code compares bands *against each other*, so the band
that is loudest in absolute terms always wins — and that's the bass, nearly
always.

**Fix:** compare each band against **its own rolling average**, and use the
ratio. A bass line that is always loud then stops being interesting; it only
lights up when it's louder *than it usually is*. The reference project calls
this an "exertion" score:

```
exertion(band) = current_energy(band) / rolling_average_energy(band)
```

Implementation notes:

- Keep a rolling average per band (exponential moving average is fine and
  cheap: `avg = avg * (1 - a) + current * a`, with `a` around 0.01–0.05 at
  30 Hz, i.e. a window of roughly 1–3 seconds).
- Guard against division by zero and against the silence case (when the track
  is paused, every band's average decays and noise gets amplified into wild
  colours). A simple absolute-energy gate below which output stays dark is
  the usual remedy.
- This can be applied *underneath* the existing modes: `spectrum_rgb` with
  exertion values instead of raw averages should already look markedly better,
  without any new mode being added.

---

## 2. Spectral centroid → hue (new mode: `centroid_hue`)

**Idea:** the spectral centroid is the "centre of mass" of the spectrum, and it
corresponds closely to the perceived *brightness* of a sound — high centroid
means a bright/sharp sound, low means dark/warm. That's a far more natural
basis for colour than three separate bands, because it's a single number that
maps cleanly onto a colour wheel.

**Mapping:**

- centroid (normalised 0.0–1.0 across the frame) → **hue**: low = warm
  (red/orange), high = cool (cyan/blue). Pick the exact arc by ear.
- overall energy → **brightness**
- optionally: spread of the spectrum → **saturation** (narrow/tonal = saturated,
  broad/noisy = washed out)

**Computing it from cava data:** the centroid is the weighted mean bar index,
weighted by bar value:

```
centroid = sum(i * value[i]) / sum(value[i])
```

Normalise by dividing by the number of bars. Note the log-spacing caveat above:
the index is not linear in frequency, which for this purpose is arguably a
*feature* (it roughly matches how we hear pitch), but it should be a conscious
choice and documented as such.

**Colour space:** this mode needs HSV→RGB conversion, since it works in hue
rather than RGB directly. `LightColorCommand` takes 16-bit RGB, so convert at
the end. `colorsys` in the standard library is sufficient — no new dependency.

---

## 3. Onset detection → flashes on the beat (new mode: `onset_pulse`)

**Idea:** rather than following volume continuously, detect the *moment* a
drum hit or note starts and flash on that. This is what makes lighting feel
like it's on the beat rather than merely following loudness.

**Standard approach** (three stages, of which only the first is needed here):

1. **Onset detection** via spectral flux — detect rapid rises in energy across
   frequency bands
2. Periodicity estimation
3. Beat location estimation

Stages 2 and 3 give real tempo tracking; that's out of scope. Stage 1 alone is
cheap and already gives a convincing effect.

**Spectral flux from cava frames:**

```
flux = sum(max(0, current[i] - previous[i]) for i in bars)
```

Only positive differences count (energy going *up*). Then:

- Keep a rolling average and standard deviation of the flux.
- An onset is a flux value exceeding `mean + k * stddev` (tune k, start around
  1.5–2.0).
- Apply a **cooldown** after each detected onset (see below).

**Behaviour:** flash to full brightness on an onset, then decay exponentially
back to a base level. The decay rate should be tunable — fast decay for punchy,
slow for a smoother pulse.

---

## Two details worth getting right

**Circular hue interpolation.** Once working in hue rather than RGB, smoothing
must go the short way around the wheel. Interpolating from orange (0.1) to
magenta (0.9) linearly drags through cyan (0.5) and produces muddy
intermediate colours; it should cross through red (0.0) instead. Implement a
circular exponential moving average — take the shorter arc.

**Deliberate restraint.** Professional lighting practice uses inertia and
blanking on purpose, and it's directly relevant here:

- During dense/intense passages, *increase* colour inertia rather than
  decreasing it. Without this the colour flickers violently between bass and
  hi-hats and just looks like noise.
- Give flashes a hard cooldown (~120 ms is the figure the reference project
  uses) so they land on the groove instead of firing on every hi-hat.

Both are a few lines each and matter more for the perceived result than any
amount of extra analysis sophistication.

---

## Suggested order of work

1. Add rolling-average/exertion normalisation, applied to the existing modes.
   Test by ear — this alone may resolve most of the complaint.
2. Add `centroid_hue` with HSV mapping and circular smoothing.
3. Add `onset_pulse` with spectral flux, threshold and cooldown.
4. Expose the new tunables (EMA window, onset threshold, decay rate, cooldown)
   as profile fields with sensible defaults, same pattern as the existing
   `sensitivity` / `brightness_floor` / `bars`.

Unit tests: the existing `tests/test_sync_engine.py` pattern (synthetic frames
in, commands out) covers this well — silence, full scale, a sudden spike for
onset detection, and a check that circular interpolation takes the short arc.

## Sources

- Onset detection / spectral flux / beat tracking pipeline:
  https://blog.paperspace.com/audio-analysis-processing-maching-learning/
- Spectral centroid as perceived brightness:
  https://www.runcomfy.com/comfyui-nodes/deforum-comfy-nodes/SpectralCentroid
- Exertion scoring, circular hue mapping, colour block inertia, strobe
  blanking: https://github.com/CanYuzbey/music-reactive-lighting
