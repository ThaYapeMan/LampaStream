# HueSync effect engine — design spec

Reimplementation brief based on the design of established music-reactive Hue
apps (Light DJ, Hue Essentials) and Music Assistant's Hue Entertainment plugin.

**Note on provenance:** Light DJ and Hue Essentials are closed-source iOS/Android
apps. Nothing here is ported code — this is a specification derived from their
documented behaviour and feature descriptions. Music Assistant's plugin is open
source and uses the same `hue-entertainment` library HueSync uses, so its
documented modes are a directly comparable reference.

---

## The core architectural change: two layers, not one mode

This is the single most important idea and it changes the shape of the engine.

Light DJ does not ask the user to pick one behaviour. It runs **two effects
simultaneously**:

- a **Mellow layer** — slower, drifting, runs in the background when the music
  is calm
- an **Active layer** — triggers during the louder, denser parts of a song

The music decides which dominates. Their description: lights get active during
intense parts of a song and flowy with softer melodies.

HueSync currently has one mode running the whole time with fixed behaviour,
which is why it feels monotonous regardless of what the music does.

**Implementation sketch:**

```
energy = normalised overall loudness (already available post-BandNormaliser)
mix = smoothstep(energy, low_threshold, high_threshold)   # 0.0 .. 1.0

mellow_colour = mellow_layer.render(frame, t)
active_colour = active_layer.render(frame, t)
final = lerp(mellow_colour, active_colour, mix)
```

`mix` needs its own smoothing (slower rise, slower fall) so the layers
crossfade rather than flicker between each other. This is where the earlier
"deliberate inertia" note belongs.

---

## Layer 2: Active effects

Light DJ ships four, and the names describe the behaviour well enough to
reimplement:

### Splotches
Random subsets of lights take a colour from the palette, others stay dim.
Reassign on onsets. Feels like patches of colour appearing around the room.

### Fireworks
On an onset, one light flashes bright then decays quickly while neighbouring
lights get a weaker, delayed version — a burst radiating outward. Needs the
spatial positions (see below).

### Pulses
All lights breathe together with the beat: brightness envelope with a fast
attack on the onset and an exponential decay. The simplest of the four, and the
closest to HueSync's existing `mono_pulse`.

### Flashes
Hard, short brightness spikes on onsets, back to near-black between them. The
most aggressive. Needs a cooldown (~120ms) or it fires on every hi-hat.

Each takes the palette as input, so the colour choice is decoupled from the
motion.

---

## Layer 1: Mellow effects

Less documented, but the described behaviour is a slow drift: gentle colour
movement, low contrast, no hard transitions. Music Assistant's equivalent modes
are useful here — their **Smooth** mode is gentle spectrum-driven brightness
with a slowly drifting palette that cycles colour on the beat, and **Ambient**
does colour cycling on the beat with saturation reacting to the bass and no
brightness modulation at all, described as best for relaxed listening.

Two mellow layers is probably enough to start: a drifting gradient, and a
bass-driven saturation shift with constant brightness.

---

## Spatial effects — currently unused capability

Light DJ's **Groove Wave** sends waves of colour across the room, and their
Hue Entertainment support is explicitly described as enabling *location-based*
and *spatial* effects.

HueSync throws this away: every light in the area gets the same colour. But
`LightChannel` from the `hue-entertainment` library carries a **position**
(x, y, z) per light, set when the Entertainment Area was configured in the Hue
app.

With positions available, a wave is straightforward:

```
phase = (t * speed) - (light.position.x * wavelength)
brightness = envelope(phase)
```

The same positions make Fireworks work properly (burst radiating from one
light outward) and let Splotches cluster spatially rather than randomly.

This is likely the single biggest visual improvement available, because it
turns a room full of synchronised bulbs into something that has direction and
movement.

---

## Palettes, not computed colours

Light DJ lets the user pick up to three colours, or lets the app choose when to
change the colour theme using its own music analysis. Crucially the colours are
**chosen from a set**, not derived from spectral content — which is why they
always look intentional.

For HueSync:

- A palette is 2-4 colours.
- Ship a handful (warm, cool, neon, monochrome, rainbow) and let a profile pick
  one.
- Effects index *into* the palette; they never compute an arbitrary RGB value.
- Change palette on musical boundaries (a sustained energy change, or every N
  beats), not continuously. Light DJ describes colours changing "at just the
  right moment" — the point is that colour change is an *event*, not a drift.

This directly replaces the current `spectrum_rgb` approach, which produces
whatever colour the spectrum implies — and for most music that is a muddy
yellow-ish region.

---

## Latency compensation

Music Assistant exposes a **light latency in milliseconds** setting: render
light updates ahead of the audio to offset the Hue bridge and network delay,
range 0-3000ms, default 20.

HueSync has nothing like this, and it matters: the lights are inherently behind
the audio because of the bridge, the network, and the buffering in the
squeezelite → cava → FIFO chain. A user-tunable offset is the pragmatic fix.

Add `light_latency_ms` as a profile field. Implementation: keep a short ring
buffer of recent frames and render from `now - latency` — or, more simply,
accept that the offset can only be positive (lights ahead of audio) if the
audio pipeline is itself delayed, which for a *visualiser-only* virtual player
it effectively is.

---

## Tempo controls

Light DJ has manual tempo controls with double-time and half-time at the press
of a button. Worth having as a profile setting once onset detection works:
effects that cycle on the beat can be made to cycle on every other beat, or
twice per beat.

---

## Proposed structure

```
sync_engine.py
├── BandNormaliser          (exists)
├── OnsetDetector           (new — spectral flux + threshold + cooldown)
├── Palette                 (new — named colour sets)
├── layers/
│   ├── base.py             (Layer interface: render(frame, features, t) -> per-channel colours)
│   ├── mellow_drift.py
│   ├── mellow_ambient.py
│   ├── active_splotches.py
│   ├── active_fireworks.py
│   ├── active_pulses.py
│   ├── active_flashes.py
│   └── active_wave.py      (Groove Wave equivalent)
└── LayerMixer              (new — energy-driven crossfade between two layers)
```

A `Profile` then specifies: mellow layer, active layer, palette, crossfade
thresholds, latency, sensitivity — rather than a single `color_mode`.

The existing three modes stay as they are for backwards compatibility with
saved profiles.

---

## Order of work

1. **Positions** — fetch and store `LightChannel.position` per channel. Without
   this, nothing spatial is possible. Small change, unlocks the most.
2. **Palettes** — replace computed colour with palette indexing.
3. **OnsetDetector** — spectral flux with cooldown; all Active effects need it.
4. **Two-layer mixer** with one mellow and one active layer to prove the shape.
5. **Remaining effects**, one at a time, each testable by ear.
6. **Latency setting.**

Steps 1-4 together are what turns this from "reacts to audio" into "looks
designed".

## Sources

- Light DJ active effects (Splotches, Fireworks, Pulses, Flashes), Mellow vs
  Active layering, Groove Wave, tempo controls, palette selection:
  https://lightdjapp.com/android and https://lightdjapp.com/ios
- Music Assistant Hue Entertainment plugin modes and light latency setting:
  https://www.music-assistant.io/plugins/hue-entertainment/
- `hue-entertainment` library (LightChannel positions, EntertainmentArea):
  https://github.com/music-assistant/hue-entertainment
