# HueSync — analysis chain and player architecture

Companion to `HueSync_effect_engine_spec.md`. That document covers *what the
lights do*; this one covers *how the audio is analysed* and *how areas are
exposed as players*.

Three sources, three different things taken from each:

| Source | What we take | What we do not take |
|---|---|---|
| LedFx | the analysis chain | its code (GPL-3; this project is MIT) |
| Light DJ / Hue Essentials | the effect designs | nothing portable — closed source |
| Music Assistant | the player model | the interface |

---

# Part 1 — Analysis chain (LedFx's method, adapted)

## What LedFx does

Their [melbank documentation](https://docs.ledfx.app/en/latest/developer/melbanks.html)
describes the full pipeline:

1. **FFT**, window size 4096, on audio resampled to 30000 Hz. The reduced rate
   is deliberate: it increases frequency resolution for bass and concentrates
   processing on the range that matters. Result: ~7.3 Hz per bin.
2. **Mel filterbank** — triangular filters on the mel scale, 24 bins by
   default, `matt_mel` coefficients. Narrow bands low, wide bands high,
   matching human hearing.
3. **Three cumulative melbanks** at different resolutions, all starting at
   20 Hz: 20-350 (bass detail), 20-2000 (bass through mid), 20-15000 (full).
   An effect automatically gets the smallest bank covering its range.
4. **Filters**: `mel_gain` (automatic gain control), `mel_smoothing` (temporal),
   `common_filter`, and `diff_filter`.
5. **Peak isolation** — a non-linear power scaling (default 0.4) that makes
   bright regions brighter and dim regions dimmer, described in their docs as
   producing more "punchy" visuals.
6. **aubio** separately, for pitch and onset detection — exposed in their
   config as selectable pitch and onset methods.

## Mapping that onto HueSync

cava already performs steps 1-2 approximately: it does the FFT and produces
log-spaced bars, which is close to (not identical to) a mel distribution. We
receive those bars as bytes over the FIFO.

| LedFx stage | HueSync status |
|---|---|
| FFT + frequency binning | cava does this |
| Frequency range cap | **missing** — see the v2 brief; cava's cutoffs must be set explicitly, this is what causes the yellow |
| `mel_gain` (AGC) | done — `BandNormaliser` |
| `mel_smoothing` | partially — the 30 Hz send loop smooths implicitly, but there is no explicit temporal filter |
| `diff_filter` | **missing** — this is essentially onset energy |
| Peak isolation | **missing** |
| Multi-resolution banks | **missing** — we have one flat frame |
| aubio onset/pitch | **missing** |

## What to add, in order

### 1. Peak isolation

A single exponent applied after normalisation:

```python
value = value ** (1.0 - peak_isolation)     # peak_isolation 0.0 .. 1.0
```

0.0 = linear, 0.4 = LedFx's default, higher = punchier. One profile field.

Cheap, immediately audible in the result, no new state.

### 2. Diff filter → onset energy

LedFx's `diff_filter` is the difference between the current value and a
smoothed version of it. That is the same quantity as spectral flux:

```python
flux = sum(max(0, current[i] - smoothed[i]) for i in bars)
```

Keep a rolling mean and standard deviation of `flux`; an onset is
`flux > mean + k * stddev`, with a cooldown (~120 ms) so it lands on the groove
rather than on every hi-hat.

This gives the Active layer in the effect spec something to trigger on, without
adding aubio or numpy.

### 3. Multi-resolution bands

Rather than three separate FFTs (cava gives us one frame), take three
*overlapping slices* of the same frame with mel-like proportions:

- **bass**: lower ~20% of bars
- **mid**: lower ~55% of bars
- **full**: all bars

Note these are cumulative like LedFx's, not exclusive. Effects pick the one
matching what they react to: Pulses on bass, palette drift on full.

The current code splits 0-15% / 15-50% / 50-100% as *exclusive* bands, which is
both the wrong proportion and the wrong model.

### 4. aubio — deliberately not now

aubio would give proper onset, tempo and pitch detection. It is also a C
library with Python bindings and real CPU cost, on an LXC with 2 vCPU already
running squeezelite and cava.

Step 2 gives usable onsets from data we already have. Revisit aubio only if
onset quality proves to be the limiting factor after the effect engine exists.

---

# Part 2 — Player architecture (Music Assistant's model)

## What they do

Music Assistant's
[Hue Lights Sync plugin](https://www.music-assistant.io/plugins/hue-entertainment/)
uses a model worth copying:

- Each **Entertainment Area on the bridge appears as its own light player**.
- You **join a light player to an active audio player or group**, and the
  lights start reacting to whatever that group is playing.
- **Multiple bridges** are supported — the plugin is added once per bridge.
- Only one Entertainment Area per bridge can stream at a time (a bridge
  limitation, same one HueSync already enforces).
- They expose **light latency in milliseconds** (0-3000, default 20) to render
  light updates ahead of the audio and offset bridge and network delay.

**Take the model, not the interface.** The MA UI is not a reference for
HueSync's GUI.

## How this maps onto HueSync

HueSync's current model is a *profile*: one saved configuration that you
activate manually, which starts a virtual squeezelite player under the covers.
That conflates two separate things:

- **which Entertainment Area to drive** (a property of the room)
- **which audio to react to** (a property of the moment)

The MA model separates them. Translated to LMS:

- Each Entertainment Area becomes a **virtual LMS player** in its own right,
  named after the area.
- The user syncs that player to whatever they are listening on, using LMS's
  own multi-room sync — exactly as they would with any other player.
- No "activate profile" step: if the virtual player is synced and audio is
  flowing, the lights react. If it is not synced, nothing happens.

This is a better fit for LMS than the current design, because syncing players
is the native idiom users already know, and it removes a concept (the manual
activate/deactivate) that has already been the source of several bugs.

### Practical consequences

- **One squeezelite instance per Entertainment Area**, not one per active
  profile. They can all run continuously; a player that is not synced simply
  receives no audio.
- The **single-stream-per-bridge constraint still applies**: if two areas on
  the same bridge are both synced and playing, only one can stream. Decide the
  behaviour deliberately (last one wins, or refuse the second with a clear
  message in the GUI) rather than letting the bridge reject it.
- Multiple bridges then work naturally: one area per bridge can be active
  simultaneously.
- The GUI becomes simpler, not more complex: it configures areas and their
  effect settings; *control* moves to the LMS controller app where it belongs.

### Latency

Add `light_latency_ms` as a per-area setting, default 20, range 0-3000. Even
without a full frame ring buffer, exposing the delay as a tunable is the
pragmatic fix for "the lights feel behind the music".

---

# Combined shape

```
LMS
 └─ virtual player per Entertainment Area (squeezelite -v)
     └─ shared memory
         └─ cava (cutoffs set explicitly, 20Hz-12kHz)
             └─ FIFO
                 └─ Analysis:  BandNormaliser (AGC)
                              → peak isolation
                              → cumulative bands (bass / mid / full)
                              → diff filter → onset detector
                 └─ Effects:   mellow layer + active layer, crossfaded on energy
                              (see HueSync_effect_engine_spec.md)
                 └─ Palette:   curated colour sets, changed on musical events
                 └─ Spatial:   per-light positions from LightChannel
                 └─ Latency:   render offset in ms
                     └─ hue-entertainment → bridge → Entertainment Area
```

## Order of work across both documents

1. cava frequency cutoffs (v2 brief, step 1) — fixes the yellow
2. `LightChannel.position` capture (effect spec, step 1) — unlocks spatial
3. Peak isolation (this doc, step 1)
4. Palettes (effect spec, step 2)
5. Onset detector via diff filter (this doc, step 2)
6. Two-layer mixer (effect spec, step 4)
7. Player-per-area model (this doc, part 2) — the largest change, worth doing
   only once the effects are worth driving
8. Latency setting

Steps 1-6 are incremental and individually testable. Step 7 is a restructure
and should be its own piece of work.
