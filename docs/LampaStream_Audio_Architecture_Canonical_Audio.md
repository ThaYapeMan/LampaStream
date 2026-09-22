# HueSync Audio Architecture --- Canonical Audio & Analysis Backends

## Status

This document defines the **target architecture and research
hypothesis** for the next HueSync DSP phase.

It is intentionally **not yet an implementation decision**. The existing
LMS/CAVA and AirPlay/PCM paths must first be audited and measured
against this model before any architectural refactor is performed.

------------------------------------------------------------------------

## 1. Core principle

Different audio sources should not be analysed as technically different
kinds of audio if that can be avoided.

HueSync should first convert source-specific audio into a **canonical
audio representation**, and only then perform musical analysis.

In short:

> **First normalize transport. Then analyse. Then normalize/condition
> features.**

This prevents comparisons between sources from becoming an
apples-to-oranges comparison.

------------------------------------------------------------------------

## 2. Target data flow

``` text
Apple Music ────┐
YouTube ────────┤
Other apps ─────┘
        ↓
     AirPlay ───────┐
LMS ────────────────┤
Future source ──────┤
                    ↓
             Source Adapter
               ↓
        Canonical PCM
               ↓
       Analysis Backend
        ┌──────┴──────┐
        ↓             ↓
   HueSync DSP       CAVA
        │             │
        └──────┬──────┘
               ↓
      Canonical Audio Features
               ↓
      ┌────────┴────────┐
      ↓                 ↓
   Effects        Energy Profile
```

The important architectural boundaries are:

``` text
SOURCE
"Where does the audio come from?"
        ↓
SOURCE ADAPTER / CANONICAL AUDIO
"What audio do we actually have?"
        ↓
ANALYSER
"What is happening in the music?"
        ↓
FEATURE CONDITIONING
"Make those measurements stable and comparable"
        ↓
AUDIO FEATURES
"level, bands, onset, energy..."
        ↓
LIGHTING LOGIC
"What should the lights do?"
```

------------------------------------------------------------------------

## 3. PCM is not an analyser

This distinction is fundamental.

### PCM

PCM is an **audio representation**.

It represents decoded audio samples. It is the material an analyser can
consume.

### HueSync DSP

HueSync's native DSP is an **analysis backend**.

It can consume PCM and derive musical features such as:

-   level;
-   spectrum;
-   frequency bands;
-   onset/transient information;
-   energy-related measurements.

### CAVA

CAVA is also conceptually an **analysis backend**.

CAVA consumes audio and produces processed spectrum information. It
already performs part of the analysis and conditioning itself.

Therefore this model is incorrect:

``` text
Analyser:
- CAVA
- PCM
```

A cleaner conceptual model is:

``` text
Audio representation:
- PCM

Analysis backend:
- HueSync DSP
- CAVA
```

The existing HueSync `bars_source` values `cava` and `pcm_pipeline`
should therefore be treated carefully during the audit. `pcm_pipeline`
likely means that HueSync performs its own analysis of PCM, rather than
PCM itself being an analyser.

No rename is required yet.

------------------------------------------------------------------------

## 4. Source adapters

A source adapter is responsible for converting source-specific audio
transport into a predictable representation for downstream DSP.

Examples may include:

``` text
AirPlay
   ↓
AirPlay / Shairport adapter
   ↓
Canonical PCM
```

and:

``` text
LMS / Squeezelite
   ↓
LMS audio adapter
   ↓
Canonical PCM
```

The analyser should ideally not need to know whether its audio
originated from AirPlay, LMS or a future source.

### Responsibilities

The source/canonicalisation layer should ultimately establish explicitly
defined properties such as:

-   sample rate;
-   PCM sample format;
-   channel layout or mono/stereo policy;
-   amplitude convention;
-   framing;
-   sample count;
-   timing/timestamps;
-   buffering semantics.

The exact canonical values are **not yet decided**.

For example, this document does not yet mandate 44.1 kHz versus 48 kHz.

------------------------------------------------------------------------

## 5. Source normalisation is not musical normalisation

Canonicalising audio must not destroy the musical dynamics HueSync is
trying to measure.

There are two separate operations.

### Stage A --- source/transport normalisation

Purpose:

> Make different sources technically comparable.

Examples:

-   resampling to a defined rate;
-   converting sample format;
-   consistent channel handling;
-   consistent framing;
-   correct sample-time/timestamps.

### Stage B --- analysis feature conditioning

Purpose:

> Make extracted measurements stable and musically useful.

Examples may include:

-   AGC/sensitivity;
-   temporal smoothing;
-   spectral smoothing;
-   band normalisation;
-   peak isolation;
-   attack/release;
-   noise reduction.

These responsibilities must not be conflated.

``` text
SOURCE NORMALISATION
        ↓
CANONICAL PCM
        ↓
ANALYSIS
        ↓
FEATURE CONDITIONING
        ↓
CANONICAL AUDIO FEATURES
```

------------------------------------------------------------------------

## 6. Why CAVA and the current PCM path may behave differently

HueSync currently appears to have two paths at different abstraction
levels.

Conceptually:

``` text
LMS / Squeezelite
       ↓
      CAVA
       ↓
processed spectrum/bars
       ↓
HueSync features
```

versus:

``` text
AirPlay
   ↓
Shairport / PCM
   ↓
HueSync PCM analysis
   ↓
HueSync features
```

CAVA already performs significant spectrum analysis and conditioning
before HueSync receives its bars.

The native PCM path begins much closer to raw audio.

Therefore a perceived difference such as:

> "AirPlay analysis looks noisier or less stable than CAVA"

does **not** prove that AirPlay audio itself contains more noise.

Possible causes include:

-   different sample rates or formats;
-   different channel handling;
-   framing differences;
-   callback/timing jitter;
-   different gain conventions;
-   different FFT/windowing;
-   less smoothing;
-   less spectral conditioning;
-   different automatic sensitivity/gain behaviour;
-   different onset processing.

The DSP investigation must isolate these variables.

------------------------------------------------------------------------

## 7. Desired analyser abstraction

The ideal experimental architecture allows the **same canonical PCM** to
be supplied to different analysis backends:

``` text
              Canonical PCM
                   │
          ┌────────┴────────┐
          ↓                 ↓
    HueSync DSP           CAVA
          ↓                 ↓
     spectrum           spectrum
          │                 │
          └──── compare ────┘
```

This is valuable because it removes the source as a variable.

If CAVA remains substantially more stable or musically useful than
HueSync DSP when both receive equivalent audio, the difference lies in
analysis/conditioning rather than AirPlay or LMS transport.

Conversely, if the analysers behave similarly on the same canonical
input but AirPlay and LMS still differ before that point, the problem
lies upstream in source ingestion/canonicalisation.

------------------------------------------------------------------------

## 8. Canonical Audio Features

Downstream lighting logic should ideally consume a stable HueSync
feature contract rather than source-specific data.

Conceptually:

``` text
CanonicalAudioFeatures
├── level / loudness-related measurements
├── spectrum / frequency bands
├── onset / transient information
├── peak information
└── energy-related features
```

The exact schema is not fixed by this document.

The important principle is:

> Effects and Energy Profiles should consume musical features, not
> compensate for transport-specific behaviour.

This avoids logic such as:

``` text
if source == AIRPLAY:
    extra_smoothing = ...
```

unless measurements prove that a source-specific correction is
fundamentally necessary.

------------------------------------------------------------------------

## 9. Effects and Energy Profile remain downstream concerns

The desired separation of responsibilities is:

``` text
Source Adapter
= How do I obtain a reliable standard audio representation from this source?

Analyser
= What is happening musically in this audio?

Feature Conditioning
= How do I make those measurements stable and comparable?

Energy Engine
= How mellow or active is the music?

Effect
= How do I translate musical features into light?
```

This keeps transport concerns out of Effects and Energy Profiles.

------------------------------------------------------------------------

## 10. CAVA's future role is deliberately undecided

Several outcomes remain possible.

### CAVA as production analysis backend

HueSync could retain CAVA as one selectable analysis backend.

### CAVA as fallback

HueSync DSP could become primary while CAVA remains available for
compatibility or comparison.

### CAVA as benchmark/reference only

If HueSync's native DSP becomes sufficiently robust, all production
sources could eventually use the same native analyser while CAVA remains
a development/reference implementation.

Architecturally, the cleanest long-term form may be:

``` text
AirPlay ─────────┐
LMS ─────────────┤
Future source ───┤
                 ↓
          Canonical PCM
                 ↓
        HueSync Analyser
                 ↓
        Audio Features
                 ↓
       ┌─────────┴─────────┐
       ↓                   ↓
    Effects          Energy Profile
```

However, **this is a hypothesis, not a current decision**.

HueSync DSP must first demonstrate that it can equal or exceed CAVA's
stability and musical usefulness.

------------------------------------------------------------------------

## 11. Source Equivalence Test

Before Energy Engine v2 is designed or tuned, HueSync should establish
whether its input/analysis paths are technically equivalent enough for
comparison.

The same reference music should be captured or reconstructed through the
relevant paths.

At minimum, investigate:

  Measurement                           Purpose
  ------------------------------------- -------------------------------------------
  Actual sample rate                    Detect source/resampling differences
  PCM format                            Detect representation differences
  Channel layout                        Detect stereo/downmix differences
  Samples per frame                     Verify framing
  Actual `dt` / sample-time             Detect timing assumptions and jitter
  RMS per frame                         Compare level
  Peak per frame                        Detect clipping/transient differences
  DC offset                             Detect capture problems
  Left/right RMS                        Detect channel imbalance/downmix problems
  Silence/noise floor                   Measure actual PCM noise
  FFT/band energy                       Compare spectral representation
  Frame-to-frame band variance          Quantify perceived analyser jitter
  CAVA bars                             Reference output
  Native PCM bars before conditioning   Isolate raw analyser behaviour
  Native PCM bars after conditioning    Measure conditioning effect
  Onset timestamps                      Compare transient timing
  Energy output                         Measure final downstream effect

Where possible, use **the same PCM material** as the input to both CAVA
and HueSync DSP.

------------------------------------------------------------------------

## 12. Timing must be based on audio/sample time

HueSync has already encountered a case where assumed processing cadence
differed from actual runtime cadence.

Therefore the audit must explicitly verify whether DSP timing uses:

-   actual audio sample count/sample rate;
-   trustworthy timestamps;
-   measured wall-clock `dt`;
-   or assumed callback/tick frequency.

Callback arrival cadence must not silently be treated as equivalent to
audio time.

This matters for:

-   EMA calculations;
-   attack/release;
-   AGC;
-   onset detection;
-   sustained energy;
-   smoothing.

------------------------------------------------------------------------

## 13. Relationship to Energy Engine v2

The canonical-audio/source-equivalence work should precede the planned
Energy Engine v2 comparison.

The current candidate comparison remains:

1.  current short/long RMS ratio as baseline;
2.  overall level + AGC + attack/release;
3.  frequency-weighted level + AGC + attack/release.

However, tuning a new Energy Engine before source equivalence is
understood risks compensating for a problem that occurs earlier in the
pipeline.

Therefore the intended order is:

``` text
1. Current audio architecture audit
2. Source equivalence measurements
3. Decide minimal canonical-audio architecture
4. Implement only the necessary architectural changes
5. Validate source equivalence
6. Energy Engine v2 experiment
7. Choose/tune production energy algorithm
```

------------------------------------------------------------------------

## 14. Basis for the next Claude Code prompt

This document should be the architectural basis for the next DSP-related
Claude Code work, but **not as an instruction to immediately refactor
the codebase**.

The first CC prompt should be an **Audio Architecture Audit**.

CC should:

-   reconstruct the current LMS/CAVA data path;
-   reconstruct the current AirPlay/PCM data path;
-   identify every format/rate/channel/framing/timing boundary;
-   document where CAVA performs processing that native HueSync DSP does
    or does not perform;
-   identify the actual meaning and implementation of `bars_source`;
-   inventory existing gain, normalisation, smoothing, FFT/windowing,
    onset and timing behaviour;
-   determine whether both paths can be fed equivalent PCM for
    controlled comparison;
-   design a Source Equivalence Test using existing diagnostic/capture
    facilities where possible;
-   identify the smallest architectural changes that would be required
    to introduce a canonical-audio boundary;
-   report findings before changing architecture.

### Hard constraint for that prompt

> **Audit and measure first. Do not implement the target architecture
> merely because it is described in this document.**

The current architecture may contain constraints or useful mechanisms
that this conceptual model does not yet account for.

------------------------------------------------------------------------

## 15. Decisions explicitly deferred

The following are **not decided by this document**:

-   canonical sample rate;
-   canonical PCM sample format;
-   mono versus stereo canonical representation;
-   exact frame size;
-   buffering strategy;
-   whether CAVA remains in production;
-   whether `bars_source` should be renamed/restructured;
-   final `AudioFeatures` schema;
-   final feature-conditioning algorithms;
-   final AGC parameters;
-   final smoothing parameters;
-   Energy Engine v2 algorithm;
-   onset fusion;
-   beat/phrase detection;
-   ML-based analysis.

These decisions require measurements.

------------------------------------------------------------------------

## 16. Architectural principle

The intended long-term principle can be summarized as:

> **Sources adapt. Analysers analyse. Features describe music. Lighting
> consumes features.**

Or as a pipeline:

``` text
SOURCE
   ↓
SOURCE ADAPTER
   ↓
CANONICAL AUDIO
   ↓
ANALYSIS BACKEND
   ↓
FEATURE CONDITIONING
   ↓
CANONICAL AUDIO FEATURES
   ↓
EFFECTS / ENERGY PROFILE
```

This separation should make HueSync easier to test, compare, debug and
extend while preventing source-specific transport behaviour from leaking
into musical lighting logic.
