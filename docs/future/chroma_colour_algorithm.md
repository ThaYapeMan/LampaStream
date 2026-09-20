# LampaStream — chroma-based colour mapping

The principled answer to "which colour should this music be". Replaces the
ad-hoc `bass_brightness` mode, which had no basis in anything and looks it.

---

## Why the current modes are weak

| Mode | What it does | Why it disappoints |
|---|---|---|
| `spectrum_rgb` | bass→R, mid→G, treble→B | colour is whatever the spectrum implies; for most music a muddy yellow region |
| `bass_brightness` | fixed warm hue, brightness follows bass | colour never changes; it is a VU meter with an orange filter |
| `mono_pulse` | single colour, brightness follows loudness | honest but minimal |

None of them has any *musical* meaning. The colour does not correspond to
anything a listener perceives.

For reference: Music Assistant's Hue plugin does **not** solve this either. Its
modes do beat-synced palette cycling with saturation reacting to bass — the
colour choice itself is arbitrary, just well-timed.

---

## The established approach: pitch class → hue via the circle of fifths

Mapping pitch classes to hue by aligning related keys with related colours goes
back to Scriabin, and has been developed properly in music-visualisation
research (Ciuha & Vidmar, *Visualization of Concurrent Tones in Music with
Colours*; also Mardirossian & Chew).

The reasoning is structural, not decorative:

- The **circle of fifths** places pitches that sound consonant together next to
  each other, and dissonant ones opposite.
- The **colour wheel** places related colours next to each other and
  complementary ones opposite.
- Mapping one onto the other preserves the relationship: **similar-sounding
  keys get similar-looking colours.**

## Handling simultaneous notes: vector summation

The interesting part. Music is rarely one note, and averaging pitch classes
naively gives nonsense.

The paper's method: represent each pitch class as a **vector** pointing in its
circle-of-fifths direction on the colour wheel, weighted by that pitch's
energy. Sum the vectors. Then:

- **angle of the resultant → hue**
- **magnitude of the resultant → saturation**
- **overall loudness → brightness/value**

Consonance and dissonance fall out of the arithmetic for free:

- A consonant chord's pitches are adjacent on the circle → vectors point the
  same way → long resultant → **saturated** colour
- A dissonant cluster's pitches are spread out → vectors partially cancel →
  short resultant → **desaturated**, washed-out colour
- Silence or noise → near-zero resultant → grey

This is why the approach is worth the effort: three musical dimensions map onto
three colour dimensions, and each mapping means something.

Note: the paper argues the plain circle of fifths has a weakness for tones
separated by major and minor thirds, and proposes a "key spanning circle of
thirds" instead. Worth reading before finalising the pitch-to-angle table, but
the circle of fifths is a perfectly good first implementation.

---

## What this requires — the honest constraint

**A chromagram: energy per pitch class (12 bins, C through B).**

cava cannot provide this. Its 24-60 log-spaced bars are far too coarse to
resolve semitones. Computing chroma needs proper frequency resolution:

- LedFx uses FFT 4096 at 30 kHz → ~7.3 Hz per bin
- At A4 (440 Hz) neighbouring semitones are ~26 Hz apart → fine
- At A2 (110 Hz) they are ~6.5 Hz apart → marginal
- At A1 (55 Hz) ~3.3 Hz apart → not resolvable at that FFT size

In practice chroma works well in the mid and upper range and poorly in the
bass, which is acceptable — bass carries rhythm, mids and highs carry harmony,
and it is harmony we want the colour from.

**This means the direct PCM tap**, reading `/dev/shm/squeezelite-<mac>`
alongside cava, rather than consuming cava's bars. That is stage 3 in
`LampaStream_analysis_layer_options_v2.md`.

librosa provides `chroma_stft` and `chroma_cqt` under an ISC licence, so this
is available without a licence problem. CPU cost on a 2-vCPU LXC needs
measuring — chroma does not need to run at 30 Hz; a few times per second is
plenty, since harmony changes on chord boundaries, not per frame.

---

## Proposed implementation

### Analysis side

Extend `AudioFeatures`:

```python
chroma: list[float] | None      # 12 values, energy per pitch class, normalised
```

`CavaAnalyser` leaves it `None`. A new `ChromaAnalyser` fills it from a PCM
tap, running the chroma computation at a lower rate (e.g. 5-10 Hz) than the
main frame loop, and holding the last value between updates.

### Effect side

```python
CIRCLE_OF_FIFTHS = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5]   # C G D A E B F# C# G# D# A# F

def chroma_to_colour(chroma, loudness):
    x = y = 0.0
    for pitch_class, energy in enumerate(chroma):
        position = CIRCLE_OF_FIFTHS.index(pitch_class)
        angle = 2 * math.pi * position / 12
        x += energy * math.cos(angle)
        y += energy * math.sin(angle)

    hue = (math.atan2(y, x) / (2 * math.pi)) % 1.0
    total = sum(chroma) or 1.0
    saturation = min(math.hypot(x, y) / total, 1.0)
    value = loudness
    return hsv_to_rgb(hue, saturation, value)
```

Roughly twenty lines, no dependency beyond the chromagram itself.

### Smoothing

Harmony changes on chord boundaries, so the hue should move deliberately, not
jitter. Two things matter:

- **Circular interpolation on hue** — going from 0.95 to 0.05 must cross
  through 0.0, not backwards through 0.5. Interpolating the wrong way drags
  through the entire colour wheel and looks like a glitch.
- **Different time constants per channel** — hue slow (chords last seconds),
  saturation medium, brightness fast (that is where the rhythm lives).

This also fits the two-layer model: chroma drives the **Mellow layer's** colour,
while onset-driven **Active** effects flash on top in a related hue.

---

## Where this sits in the plan

It does not replace the effect engine work — it *supplies the colour* that the
effects use, in place of an arbitrary palette:

- Palettes remain useful for effects that need a curated set (Splotches,
  Fireworks picking from 2-4 colours)
- Chroma gives the **base colour** the palette can be built around, so the
  palette itself follows the music's harmony instead of being fixed

Suggested order: build the effect engine with fixed palettes first (simpler,
testable), then add `ChromaAnalyser` and let it drive palette selection. That
way the chroma work is additive and can be evaluated on its own.

---

## Fair warning

This is the most musically principled option, not necessarily the one that
looks best in a living room. Research visualisations optimise for *legibility
of musical structure*; a light show optimises for *feeling right*. Light DJ's
approach (curated palettes, energy-driven layers) may well be more enjoyable
even though it is less principled.

Best evidence would be to build both and listen. The layered architecture makes
that a fair comparison rather than a rewrite.

## Sources

- Ciuha & Vidmar, *Visualization of Concurrent Tones in Music with Colours* —
  circle of fifths to colour wheel, vector summation of concurrent tones,
  consonance as saturation: http://eprints.fri.uni-lj.si/2390/1/ACM2010.pdf
- Circle of fifths ↔ colour wheel mapping preserving key relationships:
  https://rikghosh.github.io/information-aesthetics/5.final-project/
- Music Assistant Hue plugin modes (for contrast — palette cycling, not
  harmonic): https://www.music-assistant.io/plugins/hue-entertainment/
