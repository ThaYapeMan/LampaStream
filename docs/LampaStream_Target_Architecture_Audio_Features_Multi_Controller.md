# HueSync Target Architecture

## Source-independent audio intelligence and controller-independent atmosphere output

**Status:** Target architecture / design direction\
**Scope:** Architecture and product direction only. This document does
**not** authorize immediate implementation or changes to the current DSP
phase.

------------------------------------------------------------------------

## 1. Product direction

HueSync should not be designed as a "Hue music sync application".

The longer-term target is:

> **A source-independent and device-independent realtime music-to-light
> and atmosphere engine.**

Hue is one controller ecosystem, but HueSync should also be able to
drive Nanoleaf, LIFX, LED strips, projectors, Home Assistant entities,
and future controller types without changing the meaning of the audio
analysis or Effects.

The fundamental separation is:

``` text
audio source
    !=
audio analysis
    !=
artistic behaviour
    !=
physical controller
```

Three architectural rules follow:

> **AudioFeatures are source-independent.**\
> **Effects are controller-independent.**\
> **Controllers are output adapters.**

------------------------------------------------------------------------

## 2. End-to-end target architecture

``` text
                         AUDIO SOURCES
                  AirPlay / LMS / future
                            |
                            v
                       Source Adapters
                            |
                            v
                       Canonical PCM
                            |
                            v
                   AUDIO FEATURE ENGINE
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
         Spectrum        Dynamics        Rhythm
         Analysis        Analysis        Analysis
             |              |              |
             +--------------+--------------+
                            |
                            v
                       AudioFeatures
                            |
                            v
                      EnergyProfile
                            |
                            v
                       Effect Engine
                            |
                            v
                  Abstract Light Output
                            |
              +-------------+-------------+
              |             |             |
              v             v             v
             Hue        Nanoleaf         LIFX
              |
              +----------+----------+
                         |          
                         v
                 Home Assistant
                         |
          +--------------+---------------+
          |              |               |
          v              v               v
        Tuya          LED strips     Other devices
      projector
```

The exact controller topology may differ in implementation. The
important point is that the audio and Effect layers do not need to know
which physical ecosystem ultimately renders their output.

------------------------------------------------------------------------

## 3. Canonical audio

All supported realtime audio sources should converge on a clearly
defined canonical PCM contract before musical analysis.

Conceptually:

``` text
AirPlay --------+
LMS/Squeezelite +--> source adapter --> canonical PCM
Future source --+
```

Canonicalization is technical source normalization. It should establish
known properties such as sample format, sample rate, channel policy,
frame semantics and timing/discontinuity behavior.

It must **not** flatten the musical dynamics of the signal.

This distinction is fundamental:

``` text
SOURCE NORMALISATION
        |
        v
MUSICAL ANALYSIS
        |
        v
FEATURE CONDITIONING
        |
        v
AudioFeatures
```

An analyser should consume canonical audio and should not need to know
whether that audio originated from AirPlay, LMS or another source.

------------------------------------------------------------------------

## 4. HueSync Audio Feature Contract

The central interface between DSP and lighting should be a semantic
`AudioFeatures` contract.

``` text
                 HueSync Audio Feature Contract

canonical PCM
      |
      +-- Spectrum Analysis
      |      +-- bars
      |      +-- low
      |      +-- mid
      |      +-- high
      |      +-- dominant frequency
      |      +-- spectral balance (candidate)
      |
      +-- Dynamics Analysis
      |      +-- level
      |      +-- peak
      |      +-- activity
      |
      +-- Rhythm Analysis
             +-- onset
             +-- onset strength
             +-- beat
             +-- beat strength
             +-- beat phase
             +-- tempo
             +-- tempo confidence
                       |
                       v
                 AudioFeatures
                       |
          +------------+------------+
          |                         |
          v                         v
       Effects                EnergyProfile
```

This is a **semantic contract**, not yet a frozen API schema. Individual
fields must earn their place through a concrete lighting use case and
measurable behavior.

### 4.1 Spectrum

Spectrum features describe **where** musical energy exists.

Likely consumers include spectrum-driven color and spatial Effects.

Examples:

-   `bars[]`
-   `low`
-   `mid`
-   `high`
-   `dominant_frequency`
-   potentially a compact spectral-balance feature

### 4.2 Dynamics

Dynamics features describe **how strong or active** the music is.

Examples:

-   `level` - current signal level
-   `peak` - short-duration peak intensity
-   `activity` - contextual musical activity suitable for slower
    behavioral decisions

`activity` is particularly important for EnergyProfile. It should have
one explicit meaning regardless of whether the source is LMS, AirPlay or
another future source.

### 4.3 Rhythm

Rhythm features describe **when** musically significant events occur.

Examples:

-   `onset`
-   `onset_strength`
-   `beat`
-   `beat_strength`
-   `beat_phase`
-   `tempo`
-   `tempo_confidence`

Confidence is important. A realtime analyser should be able to express
that a tempo or beat estimate is uncertain. Lighting can then degrade
gracefully rather than behaving as if every inferred beat grid is
correct.

### 4.4 Musical structure - later, not foundational

More advanced features may eventually include:

``` text
break_probability
build_probability
drop_probability
```

These should not be introduced merely to match another product.
Spectrum, dynamics and rhythm should first be stable, source-independent
and useful.

------------------------------------------------------------------------

## 5. One signal should not do every job

There is no single universal definition of "audio energy".

HueSync should distinguish at least:

``` text
LOUDNESS
How strong is the signal?

SPECTRAL ENERGY
Where is energy located across frequency?

TRANSIENT ENERGY
Did something significant happen right now?

RHYTHMIC ACTIVITY
How much beat/rhythmic activity is present?

MUSICAL ACTIVITY
Is the current musical passage relatively calm or intense?
```

These concepts serve different consumers.

A likely mapping is:

``` text
spectrum_rgb  --> spectrum bars
spatial       --> spectral distribution
flashes       --> onset / onset_strength
pulses        --> beat / beat_strength
phase motion  --> beat_phase
EnergyProfile --> activity
```

Effects should consume semantic features rather than know whether those
features came from CAVA, an FFT implementation, SuperFlux, RMS, or
another internal algorithm.

------------------------------------------------------------------------

## 6. CAVA's future role

CAVA should not be treated as ground truth.

It is a useful existing spectrum visualizer and reference backend. Its
behavior can teach HueSync which properties are useful, but a difference
between CAVA and native HueSync DSP does not imply that native DSP is
wrong.

The target direction is likely:

``` text
Squeezelite --+
AirPlay ------+--> canonical PCM --> HueSync analysis --> AudioFeatures
Future -------+
```

This would remove the architectural asymmetry in which LMS/CAVA and
native PCM sources can produce features with different semantics.

However:

> **Leaving CAVA does not mean the current native DSP is automatically
> correct.**

The correct migration strategy is:

``` text
characterize CAVA
      |
      v
identify useful behavior
      |
      v
choose the behavior HueSync actually wants
      |
      v
implement/retain standard DSP techniques
      |
      v
validate objectively
      |
      v
retire CAVA only when its useful role has been replaced
```

Current deterministic CAVA-vs-native work should therefore be
interpreted as **DSP characterization**, not CAVA equivalence.

------------------------------------------------------------------------

## 7. Better than Lightjams: the HueSync approach

The objective should not be to beat Lightjams by having a longer feature
list.

Lightjams is useful prior art because mature music-lighting systems
separate spectrum information from concepts such as level/energy, beat
and higher-level musical events.

HueSync can differentiate itself by making those concepts part of a
cleaner, source-independent and observable architecture specifically
optimized for automatic atmosphere and lighting.

### 7.1 Do not reinvent established DSP

HueSync does not need a proprietary FFT, RMS calculation or
onset-detection theory merely to be unique.

Established building blocks should be preferred where they solve the
problem:

``` text
PCM
 |
 +-- RMS / peak / loudness
 +-- FFT / STFT
 +-- logarithmic or perceptual frequency bands
 +-- spectral flux
 +-- onset detection
 +-- beat tracking
 +-- BPM / phase estimation
 +-- adaptive normalization
 +-- temporal smoothing
 +-- hysteresis
```

HueSync's value is primarily in **feature semantics, conditioning,
orchestration and lighting behavior**, not in unnecessarily
reimplementing signal-processing mathematics.

### 7.2 Source invariance

The same musical material should have essentially the same musical
interpretation regardless of transport:

``` text
same music via LMS
same music via AirPlay
same music via future source

             |
             v
      equivalent AudioFeatures
```

Transport differences should not become artistic differences unless
explicitly intended.

### 7.3 Preserve musical dynamics

Technical normalization must not erase musical structure.

An aggressive automatic gain system may make a spectrum visually
attractive while gradually making a quiet intro look as "energetic" as a
climax.

HueSync should therefore separate:

``` text
technical input conditioning
        !=
musical dynamics interpretation
```

Different features may require different conditioning.

For example:

``` text
spectrum --> visual stability conditioning
onset    --> fast transient-sensitive conditioning
level    --> level normalization
activity --> slower musical-context model
```

There should not automatically be one global AGC that determines every
musical feature.

### 7.4 Multiple timescales

Music exists simultaneously at different timescales.

A useful conceptual model is:

``` text
milliseconds       spectral/transient detail
tens-hundreds ms   onset and beat strength
hundreds ms-seconds local activity
seconds-tens sec   musical context
```

HueSync should explicitly use appropriate temporal behavior per feature
instead of forcing all analysis through one smoothing constant.

### 7.5 Confidence-aware analysis

Where an estimate can be uncertain, uncertainty should be represented.

For example:

``` text
tempo = 128 BPM
tempo_confidence = 0.93
```

is more useful than blindly asserting a 128 BPM beat grid.

A consumer can then choose:

``` text
high confidence --> phase/beat synchronized behavior
low confidence  --> onset/reactive fallback
```

This makes the lighting more robust when music is rhythmically
ambiguous.

### 7.6 Explainable lighting

A major HueSync differentiator should be observability.

Runtime diagnostics should make the chain understandable:

``` text
Spectrum       [...]
Level          0.62
Activity       0.78
Onset strength 0.91
Tempo          126.4 BPM
Confidence     0.89
Beat phase     0.37

EnergyProfile:
activity 0.78 --> blend 73%
```

This directly follows HueSync's product principles:

> **Observable where it represents runtime.**\
> **Explicit where it represents relationships.**

The goal is that "Why did the lights do that?" can be answered from the
runtime state rather than by guessing at hidden DSP.

### 7.7 Objective definition of "better"

HueSync is not better because it has more knobs or features.

For its intended use, it should aim to demonstrate:

1.  **Source invariance** - equivalent music produces equivalent
    features through different source adapters.
2.  **Volume robustness** - reasonable source-level changes do not
    fundamentally alter musical interpretation.
3.  **Dynamics preservation** - quiet, build and climax remain
    meaningfully distinct.
4.  **Rhythmic reliability** - onset and beat behavior is musically
    useful, with uncertainty represented where appropriate.
5.  **Explainability** - the path from audio feature to
    Effect/EnergyProfile behavior is inspectable.
6.  **Device independence** - the same musical interpretation can drive
    very different output ecosystems.
7.  **Graceful capability adaptation** - fast streaming lights and slow
    ambient devices can participate in the same atmosphere without
    pretending they have identical capabilities.

This is the path by which HueSync can become better suited to automatic
multi-ecosystem music lighting than a more generic lighting-analysis
system.

------------------------------------------------------------------------

## 8. Controller-independent Effects

Effects should express artistic intent without containing
controller-specific implementation logic.

Avoid:

``` text
Effect --> Hue-specific command
```

Prefer:

``` text
AudioFeatures
     |
     v
Effect
     |
     v
Abstract Light Output
     |
     v
Controller Adapter
```

A controller adapter is responsible for translating abstract output into
the native capabilities and protocol of Hue, Nanoleaf, LIFX, Home
Assistant or another target.

This permits one Effect to retain the same musical meaning across
ecosystems.

------------------------------------------------------------------------

## 9. Capability-driven output

Not every device can or should be driven at the same rate or with the
same semantics.

Possible capabilities include:

``` text
RGB_COLOR
BRIGHTNESS
COLOR_TEMPERATURE
TRANSITION
SPATIAL
SEGMENTS
FAST_STREAMING
SCENE
EFFECT
SPEED
SWITCH
```

These names are conceptual and are not yet a frozen implementation API.

A high-rate entertainment light may support continuous per-frame output:

``` text
beat     --> pulse
spectrum --> color
activity --> intensity
```

A Wi-Fi projector may instead be suitable for slower atmospheric state
changes:

``` text
LOW activity
--> cool color
--> slow internal effect
--> lower brightness

MID activity
--> richer color
--> medium movement

HIGH activity
--> warmer/intense color
--> faster internal effect
--> higher brightness
```

Both devices consume the same musical interpretation. Their adapters
realize that intent according to their capabilities and safe/useful
update rates.

------------------------------------------------------------------------

## 10. Tuya projectors and other atmosphere devices

A Tuya-based projector is a good example of why HueSync should not model
every output as a high-rate RGB lamp.

The exact controls available on a particular Tuya device must be
discovered from the actual device/integration. Depending on the device,
useful capabilities may include color, brightness, scenes, effect
selection, effect speed and power.

HueSync should not require a bespoke native driver for every inexpensive
or obscure smart-lighting device.

Instead there should be two complementary strategies:

``` text
Latency-sensitive / high-rate:
HueSync --> native controller adapter --> device

Long-tail ecosystem:
HueSync --> Home Assistant --> device/integration
```

This allows native integrations where realtime performance matters,
while Home Assistant can provide broad compatibility for projectors,
Zigbee devices, Wi-Fi lights, LED controllers and other atmosphere
hardware.

Home Assistant should therefore be considered a potential **first-class
Controller backend**, not merely a Tuya workaround.

It should not, however, become mandatory middleware for native
controllers.

------------------------------------------------------------------------

## 11. LED strips

LED strips can range from a single RGB light to highly addressable
realtime pixel systems.

The capability model should accommodate this distinction.

Examples:

``` text
simple RGB strip
  --> RGB_COLOR / BRIGHTNESS / TRANSITION

addressable strip
  --> RGB_COLOR / BRIGHTNESS / SEGMENTS / FAST_STREAMING / EFFECT
```

A future controller adapter may be native or may operate through Home
Assistant or another bridge.

The Effect engine should not need to change simply because the physical
output is a strip rather than a bulb or panel.

------------------------------------------------------------------------

## 12. Zones and heterogeneous atmosphere

Conceptually, a Zone should ultimately represent a logical output area
rather than being intrinsically tied to a Hue Entertainment Area.

For example:

``` text
Living Room

Front
  - Hue Play Left
  - Hue Play Right

Back
  - Nanoleaf panels
  - LED strip

Ambient
  - Tuya projector
```

This does **not** imply that the current Zone domain model should be
refactored during the DSP phase. It is a target-architecture
consideration for the later Controller/Zone work.

The same applies to questions such as whether one Zone may span multiple
physical controllers. That decision should be made deliberately when the
output architecture is designed, not smuggled into current DSP work.

------------------------------------------------------------------------

## 13. EnergyProfile's role

EnergyProfile should remain controller-independent.

Conceptually:

``` text
AudioFeatures.activity
          |
          v
     EnergyProfile
          |
   low <-> high blend
          |
          v
      Effect Engine
```

It should consume a clearly defined musical-activity feature and
determine artistic behavior.

It should **not** consume a backend-dependent value whose meaning
changes between CAVA, native LMS and AirPlay.

This is one reason the future `activity` feature is important.

------------------------------------------------------------------------

## 14. Development strategy

The architecture above is a target, not permission to refactor
everything now.

The recommended sequence remains disciplined:

``` text
current DSP characterization
        |
        v
independent review
        |
        v
Audio Feature Contract v1
        |
        v
objective tests per feature
        |
        v
select/implement established DSP techniques
        |
        v
deterministic benchmark suite
        |
        v
real-music validation
        |
        v
stable AudioFeatures
        |
        v
Effects / EnergyProfile consume semantic features
        |
        v
Controller / Zone capability architecture
        |
        v
native + Home Assistant ecosystem expansion
```

Do not simultaneously rewrite DSP, Controllers, Zones and Effects.

The existing project scope rule remains valuable:

> **No unrelated backend feature should be introduced merely because the
> target architecture can imagine it.**

Complexity must be earned by an actual product requirement.

------------------------------------------------------------------------

## 15. Architectural north star

The target can be summarized as:

``` text
                         MUSIC
                           |
                           v
                    Canonical Audio
                           |
                           v
                  Musical Understanding
                           |
                           v
                    AudioFeatures
                           |
                           v
              Artistic Lighting Behaviour
                           |
                           v
                 Abstract Atmosphere
                           |
       +-------------------+-------------------+
       |          |          |         |       |
       v          v          v         v       v
      Hue      Nanoleaf     LIFX      LEDs   Home Assistant
                                               |
                                               v
                                  Tuya / projectors / future
```

HueSync's competitive goal is therefore not:

> "Build another spectrum visualizer."

Nor:

> "Clone Lightjams."

It is:

> **Build a source-independent, confidence-aware, observable
> music-understanding layer feeding a controller-independent realtime
> atmosphere engine.**

Established DSP should be reused where appropriate. HueSync should
differentiate through the quality and semantics of its features,
preservation of musical dynamics, explainability, Effect behavior,
capability-aware output and the ability to create one coherent musical
atmosphere across heterogeneous hardware.

That is the architectural path by which HueSync can aim to outperform
Lightjams **for its chosen problem domain**, without reinventing signal
processing simply for the sake of owning it.
