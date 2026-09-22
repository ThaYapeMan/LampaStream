# HueSync Audio Architecture v1

## Canonical PCM, source-independent analysis, semantic AudioFeatures, and a separate CAVA compatibility track

**Status:** Design direction / implementation baseline  
**Priority:** Primary audio architecture after completion of the currently running Phase 2A-R work  
**Supersedes on conflict:** Earlier target-architecture audio assumptions  
**Scope:** Audio ingestion, canonicalization, native PCM analysis, AudioFeatures, CAVA coexistence, and the boundary toward Effects/EnergyProfile. Controller-independent output direction from the earlier architecture remains valid.

---

## 1. Decision summary

HueSync will proceed with a **PCM-first audio architecture**.

All realtime audio sources should be adapted and decoded into one explicit canonical analysis representation before native musical analysis. The analyser must not need to know whether the audio originated from LMS/Squeezelite, AirPlay, an MP3 stream, TIDAL, Roon, Cast, or a future source.

The architectural target is:

```text
audio source
    ↓
source adapter / decoder
    ↓
decoded source PCM
    ↓
AudioCanonicalizer
    ↓
HueSync Analysis PCM
    ↓
Audio Feature Engine
    ↓
AudioFeatures
    ↓
Effects + EnergyProfile
```

The initial target contract for **HueSync Analysis PCM v1** is:

```text
sample rate       48,000 Hz
sample type       IEEE float32
amplitude         normalized numeric representation, nominally [-1.0, +1.0]
channels          2 (stereo)
channel order     Left, Right
time base         sample-position based, 1 / 48,000 second
discontinuities   explicit
source metadata   preserved separately
clipping          observable; not silently repaired
AGC/loudness      none in canonicalization
```

This is a technical normalization contract. It is **not** musical loudness normalization.

CAVA is **not being removed now**. It becomes a separate, non-authoritative compatibility/reference track. The current Phase 2A-R work may finish and establish a final CAVA baseline, but CAVA characterization is no longer the critical path for the native PCM architecture. CAVA may be retained, adapted, or phased out later based on evidence.

---

## 2. Product and architecture goal

HueSync is not fundamentally a Hue-only spectrum visualizer. Its target is a:

> **Source-independent and device-independent realtime music-to-light and atmosphere engine.**

The audio side should therefore obey the following rules:

> **Sources adapt and decode.**  
> **Canonicalization standardizes technical audio representation.**  
> **Analysers analyse canonical audio.**  
> **AudioFeatures describe music semantically.**  
> **Effects consume features, not source/backend details.**

The output-side rules from the existing architecture remain:

> **AudioFeatures are source-independent.**  
> **Effects are controller-independent.**  
> **Controllers are output adapters.**

The complete conceptual pipeline is:

```text
LMS / AirPlay / streams / future sources
                  ↓
             Source Adapters
                  ↓
             Decoded Audio
                  ↓
          AudioCanonicalizer
                  ↓
       HueSync Analysis PCM v1
                  ↓
          Audio Feature Engine
        ┌─────────┼─────────┐
        ↓         ↓         ↓
    Spectrum   Dynamics   Rhythm
        └─────────┼─────────┘
                  ↓
             AudioFeatures
                  ↓
       EnergyProfile / Effects
                  ↓
        Abstract Light Output
                  ↓
          Controller Adapters
```

---

## 3. Why canonical PCM is the primary boundary

A source is a transport/decoder concern, not a musical-analysis type.

HueSync should avoid architectures such as:

```text
LMS       → CAVA       → feature semantics A
AirPlay   → native DSP → feature semantics B
MP3       → special DSP→ feature semantics C
future    → ???        → feature semantics D
```

Instead:

```text
LMS / Squeezelite ─┐
AirPlay ────────────┤
MP3/AAC stream ─────┤
TIDAL path ─────────┤
Roon path ──────────┤
Cast path ──────────┤
future source ──────┘
         ↓
 source-specific decode/adaptation
         ↓
    canonical PCM
         ↓
 one HueSync analysis architecture
```

This makes adding a future source primarily an ingestion problem. Once it satisfies the canonical PCM contract, the native analyser and feature semantics should remain unchanged.

The engineering objective becomes:

> **Equivalent musical material presented through different supported source adapters should produce practically equivalent AudioFeatures, within defined tolerances.**

That is the source-invariance criterion.

---

## 4. Source diversity and what HueSync must normalize

Future source integrations may deliver or originate from many technical forms:

```text
raw PCM
MP3
AAC
ALAC
FLAC
Opus
high-resolution PCM
mono audio
stereo audio
44.1 kHz material
48 kHz material
higher-rate material
networked live streams
buffered playback
```

The analyser should not carry branches for these formats.

A compressed stream is decoded first:

```text
MP3 / AAC / FLAC / ALAC / Opus
              ↓
            decoder
              ↓
       decoded source PCM
              ↓
      AudioCanonicalizer
              ↓
      HueSync Analysis PCM
```

For example:

```text
MP3 stream, 44.1 kHz stereo
        ↓ decode
PCM, 44.1 kHz stereo
        ↓ resample + sample conversion
48 kHz float32 stereo
        ↓
HueSync Audio Feature Engine
```

A high-resolution source follows the same model:

```text
high-rate / high-bit-depth source
        ↓ decode
source PCM
        ↓ quality resample + conversion
48 kHz float32 stereo
        ↓
HueSync Audio Feature Engine
```

The source adapter owns the transport- and codec-specific work. The canonicalizer owns the conversion to the common analysis representation.

---

## 5. HueSync Analysis PCM v1

### 5.1 Sample rate: 48 kHz

The architectural target is **48,000 samples per second**.

The purpose is not to claim that 48 kHz is universally superior for playback. HueSync needs one deterministic DSP time/frequency basis that works well across music and network/AV source ecosystems.

Source material at 44.1 kHz is resampled to 48 kHz. Higher-rate source material is downsampled using an appropriate anti-aliasing resampler. A source already delivering 48 kHz requires no sample-rate conversion.

The analyser must not change its semantics depending on the original source rate.

### 5.2 Sample representation: float32

Packed integer formats such as S16_LE, S24, or S32 may remain valid transport/decoder formats, but they are not the semantic internal DSP representation.

Canonical samples should be float32, nominally:

```text
-1.0   negative full scale
 0.0   zero
+1.0   positive full scale
```

All integer decoding and scaling occurs before or at the canonicalization boundary.

This keeps FFT/STFT, RMS, peak, dynamics, onset, and future analysis code independent of source bit depth and byte layout.

### 5.3 Stereo is preserved

Canonicalization must not globally reduce stereo to:

```text
(L + R) / 2
```

Doing so destroys information before the feature extractor has decided whether that information matters. In particular, phase-opposed stereo content can cancel in such a downmix.

Analysis PCM therefore preserves Left and Right channels.

Each feature family may later define its own explicit channel policy:

```text
Spectrum    → analyse L/R appropriately, then combine if required
Dynamics    → explicit stereo level policy
Spatial     → may preserve/use channel differences
Peak        → explicit per-channel or combined definition
Mono feature→ explicit downmix only where semantically intended
```

Channel policy belongs to feature semantics, not hidden source normalization.

### 5.4 Mono sources

A mono source can be canonicalized deterministically to stereo, for example by duplication:

```text
mono → L
mono → R
```

The exact policy should be part of the canonicalizer specification and tested.

### 5.5 Timing and sample position

Canonical audio is not merely a NumPy-like array of samples. Realtime lighting needs reliable temporal semantics.

Analysis frames/chunks must be associated with a monotonically increasing canonical sample position. At 48 kHz, sample position is the primary time base:

```text
time = sample_position / 48000
```

Wall-clock timestamps may be carried for diagnostics/synchronization, but DSP progression should not depend on polling frequency when audio-time semantics are required.

This addresses a class of errors where the same audio state can accidentally be processed repeatedly merely because a consumer polls faster than a producer emits data.

### 5.6 Discontinuities and validity

Live network and streaming sources can reconnect, underrun, jump, restart, or lose data.

A gap in transport must not silently become a musical observation.

The canonical contract therefore needs an explicit discontinuity/validity mechanism. Examples include:

```text
stream start
stream restart
missing samples
decoder reset
source seek
rate/format change
buffer underrun
transport reconnect
```

The exact schema is an implementation decision, but these events must be representable.

---

## 6. What canonicalization does — and does not do

Canonicalization is **technical source normalization**.

It may perform:

```text
decode/accept decoded PCM
sample-format conversion
bit-depth scaling
resampling
channel-layout canonicalization
chunk/frame alignment
sample-position tracking
discontinuity propagation
source metadata preservation
```

It must not automatically perform:

```text
track peak normalization
loudness normalization
aggressive AGC
musical activity compression
spectrum autosensitivity
beat-dependent gain
quiet-section boosting
climax attenuation
```

The distinction is:

```text
SOURCE / FORMAT NORMALIZATION
             ↓
        canonical PCM
             ↓
       MUSICAL ANALYSIS
             ↓
FEATURE-SPECIFIC CONDITIONING
             ↓
        AudioFeatures
```

A quiet intro, build, and climax must remain meaningfully different after canonicalization.

---

## 7. Source adapters

A source adapter's responsibility is to produce correctly described decoded audio and lifecycle information.

A conceptual source-side contract is:

```text
DecodedAudioFrame
    samples
    sample_rate
    sample_format / numeric representation
    channel_count
    channel_layout
    source sample position or timing, when available
    discontinuity / validity state
    source metadata
```

This is intentionally distinct from `AnalysisPcmFrame`.

The canonicalizer converts source-side frames to the single analysis contract:

```text
DecodedAudioFrame
        ↓
AudioCanonicalizer
        ↓
AnalysisPcmFrame
```

A source adapter must not contain Effect logic, EnergyProfile logic, or source-specific versions of musical feature extraction.

### 7.1 LMS / Squeezelite

LMS/Squeezelite should eventually be able to feed the canonical PCM path directly. Existing CAVA operation is retained separately during migration.

### 7.2 AirPlay

AirPlay remains a source adapter. Its external pipe/decoder format is a transport boundary, not the permanent DSP format. The existing explicit Shairport pipe contract may remain useful for reliable ingestion, after which samples are converted to Analysis PCM.

### 7.3 MP3 and other compressed streams

MP3 is not an analysis format.

```text
MP3 network/file stream
        ↓ decoder
decoded PCM
        ↓ canonicalizer
Analysis PCM
```

Codec artifacts present in decoded audio are part of the observed source signal. Canonicalization should not attempt to reconstruct information lost by lossy compression.

### 7.4 TIDAL, Roon, and Cast

These names describe ecosystems/playback paths, not analyser types.

The integration-specific question is how a legally and technically supported HueSync source adapter obtains decoded audio or an equivalent source signal. That question is deliberately outside the Audio Feature Engine.

Once decoded PCM is available:

```text
ecosystem-specific playback
        ↓
source adapter / decoder
        ↓
decoded PCM
        ↓
canonicalizer
        ↓
Analysis PCM
```

No per-service DSP should be introduced merely because the upstream transport or codec differs.

---

## 8. Audio Feature Engine

The Audio Feature Engine consumes only canonical Analysis PCM.

Its central output is a semantic `AudioFeatures` contract.

```text
Analysis PCM
      │
      ├── Spectrum Analysis
      │
      ├── Dynamics Analysis
      │
      └── Rhythm Analysis
      │
      ↓
AudioFeatures
```

This separates **representation of music** from the algorithms used to derive it.

Effects should not know whether a feature came from an FFT implementation, spectral flux, RMS, a beat tracker, CAVA compatibility data, or another internal technique.

---

## 9. Audio Feature Contract v1 direction

The contract is semantic first; fields are admitted only when they serve a concrete lighting behavior and can be defined/tested.

### Spectrum

Spectrum answers: **where is energy located?**

Candidate features:

```text
bars[]
low
mid
high
dominant_frequency
spectral_balance   # candidate
```

Likely consumers include spectrum-driven color, spatial mapping, and frequency-aware effects.

### Dynamics

Dynamics answers: **how strong or active is the music?**

Candidate features:

```text
level
peak
activity
```

`activity` is especially important. It should become the deliberate semantic input to EnergyProfile rather than an overloaded mean spectrum or backend-dependent fallback.

### Rhythm

Rhythm answers: **when are musically significant events occurring?**

Candidate features:

```text
onset
onset_strength
beat
beat_strength
beat_phase
tempo
tempo_confidence
```

Not every candidate is authorized for immediate implementation. The contract/design phase must define the use case, semantics, timing, confidence, and testability before a field is implemented.

### Structure — later

Features such as:

```text
break_probability
build_probability
drop_probability
```

remain future work. They are not foundational to PCM-first migration and should not enter the current implementation merely to match competing systems.

---

## 10. One audio signal must not do every job

HueSync should explicitly distinguish:

```text
LOUDNESS / LEVEL
How strong is the current signal?

SPECTRUM
Where in frequency is the energy?

TRANSIENT / ONSET
Did a significant event happen now?

RHYTHM
Where are beats and rhythmic phase?

MUSICAL ACTIVITY
Is this passage relatively calm or intense in musical context?
```

These have different consumers and different useful time scales.

A target mapping is:

```text
spectrum_rgb   → spectrum bars
spatial effects→ spectral/channel distribution
flashes        → onset_strength
pulses         → beat / beat_strength
phase motion   → beat_phase
EnergyProfile  → activity
```

No single `features.full`-style scalar should implicitly stand in for all of these meanings.

---

## 11. Feature-specific conditioning

Technical canonicalization and musical conditioning are separate layers.

Different features may need different conditioning:

```text
spectrum → stable visual scaling / frequency conditioning
onset    → fast transient-sensitive conditioning
level    → explicit level semantics
activity → slower contextual model
rhythm   → timing/confidence conditioning
```

HueSync should not introduce one global AGC that determines every feature.

Useful musical dynamics must survive. Source-level robustness should be achieved in a way that does not make a quiet intro and a climax semantically identical.

---

## 12. Multiple time scales

Music exists on several time scales, and HueSync should not force all analysis through one smoothing behavior.

Conceptually:

```text
milliseconds          spectral/transient detail
tens-hundreds ms      onset and immediate rhythmic strength
hundreds ms-seconds   local activity
seconds-tens seconds  musical context
```

These are conceptual categories, not frozen constants.

Each feature should define its own latency, attack/release, windowing, and temporal semantics based on its lighting use case.

---

## 13. CAVA: separate compatibility/reference track

CAVA is **retained for now**.

It is not ground truth and it is no longer the architectural center of HueSync's audio path.

The two tracks are:

```text
PRIMARY TRACK
source → decoded PCM → canonical PCM → native HueSync analysis → AudioFeatures

CAVA TRACK
supported existing source path → CAVA → compatibility/reference behavior
```

The CAVA track has three purposes:

1. preserve existing functionality while native PCM analysis matures;
2. provide targeted reference behavior where useful;
3. allow an evidence-based later decision to retain or retire CAVA.

The current Phase 2A-R work may finish. Its output should be treated as a bounded CAVA characterization/control baseline. After that, further exhaustive CAVA equivalence work is **not a blocker** for the PCM-first track unless a concrete native-analysis question requires a targeted comparison.

HueSync should not attempt to make native DSP identical to CAVA merely for equivalence.

A difference should be evaluated as:

```text
What does CAVA do?
What does native PCM analysis do?
Why?
Which behavior better serves the HueSync feature/use case?
```

CAVA can later be phased out only when its useful production role has been replaced and migration risk is acceptable.

---

## 14. Current migration principle

The project must avoid a flag-day rewrite.

During transition, the system may temporarily contain both:

```text
LMS → CAVA path
LMS → native PCM path
AirPlay → native PCM path
```

That is acceptable as migration state.

What is not acceptable as the long-term architecture is for `AudioFeatures` to retain permanently different semantics depending on which backend happened to produce them.

The native PCM track should therefore converge toward:

```text
LMS ───────┐
AirPlay ───┤
future ────┤
streams ───┘
     ↓
canonical PCM
     ↓
same feature engine
     ↓
same AudioFeature semantics
```

---

## 15. Validation strategy

The PCM-first architecture should be validated independently of CAVA.

### 15.1 Canonicalizer tests

For each source representation, verify:

```text
sample conversion correctness
resampling correctness
channel policy
chunk-boundary invariance
partial-frame handling
sample-position continuity
discontinuity propagation
no unintended gain changes
clipping visibility
```

A source split into arbitrary chunk sizes must produce the same canonical sample sequence as the same source supplied in larger chunks.

### 15.2 Deterministic DSP signals

Native feature behavior should be characterized with deterministic signals such as:

```text
silence
steady tones
amplitude steps
multi-tone signals
short transients
stereo-only signals
opposite-phase stereo
controlled noise / broadband material
```

These tests answer feature-contract questions, not “does it look like CAVA?”

### 15.3 Real music validation

Deterministic tests are necessary but insufficient.

Representative music should verify:

```text
quiet intro remains quiet
build becomes more active
climax remains distinguishable
bass/mid/treble content maps sensibly
transients cause useful onset behavior
rhythm behavior is stable when confidence is high
ambiguous material degrades gracefully
```

### 15.4 Source-invariance tests

The same musical material should be delivered through multiple supported source paths and compared after canonicalization and at the AudioFeatures boundary.

Target:

```text
same source material
   ├─ LMS
   ├─ AirPlay
   ├─ file/test adapter
   └─ future source
          ↓
 equivalent Analysis PCM where transport permits
          ↓
 practically equivalent AudioFeatures
```

Differences caused by upstream codec loss or source-side processing must be measured and documented rather than hidden.

---

## 16. Observability

The canonical PCM and feature boundaries should support diagnostics.

HueSync should eventually be able to explain:

```text
Source
  format/rate/channels
  adapter state
  discontinuities

Canonical PCM
  48 kHz float32 stereo
  sample position
  clipping/validity
  resampling status

AudioFeatures
  spectrum
  level
  peak
  activity
  onset/strength
  rhythm/confidence

EnergyProfile
  activity → blend

Effect
  consumed features → output intent
```

This supports the product principle:

> **Observable where it represents runtime.**

It also makes source-specific failures distinguishable from analyser failures.

---

## 17. Controller-independent downstream architecture

The earlier controller-independent direction remains valid and is not changed by this document.

```text
AudioFeatures
     ↓
EnergyProfile / Effect Engine
     ↓
Abstract Light / Atmosphere Output
     ↓
Controller Adapters
     ├─ Hue
     ├─ Nanoleaf
     ├─ LIFX
     ├─ WLED / LED controllers
     ├─ Home Assistant
     └─ future
```

Effects should express artistic intent, not Hue-specific protocol commands.

Fast streaming devices and slower state-oriented atmosphere devices may realize the same musical interpretation differently according to capabilities.

Controller/Zone refactoring remains a later phase and must not be smuggled into the current audio work.

---

## 18. Relationship to EnergyProfile

EnergyProfile remains controller-independent and should consume a deliberately defined musical `activity` feature.

Target:

```text
canonical PCM
     ↓
Dynamics / Activity analysis
     ↓
AudioFeatures.activity
     ↓
EnergyProfile
     ↓
low ↔ high Effect blend
```

It must not permanently depend on backend-specific meanings such as one path using sustained RMS while another falls back to mean normalized spectrum.

The current asymmetry is migration debt to remove through the semantic AudioFeatures contract.

---

## 19. Implementation sequencing

The current Phase 2A-R run should be allowed to finish. It is the closing bounded CAVA characterization/control task, not the beginning of an endless CAVA-equivalence program.

After that, the primary sequence is:

```text
finish and review Phase 2A-R
        ↓
freeze CAVA findings as reference baseline
        ↓
Audio Feature Contract v1
        ↓
Canonical PCM contract v1
        ↓
audit current native PCM path against those contracts
        ↓
implement/test AudioCanonicalizer
        ↓
characterize native PCM features
        ↓
correct only contract-relevant native DSP issues
        ↓
validate with deterministic + real music
        ↓
LMS/native vs AirPlay/native source-invariance validation
        ↓
migrate consumers toward stable semantic AudioFeatures
        ↓
targeted CAVA comparisons only when useful
        ↓
later CAVA retention/deprecation decision
```

The exact order of the two design contracts may be iterated together, because feature requirements can constrain canonical timing/channel semantics. Neither requires tuning CAVA.

Do not simultaneously redesign Controllers, Zones, Effects, mobile UI, and DSP.

---

## 20. Non-goals for this phase

This architecture does **not** authorize:

```text
removing CAVA immediately
rewriting all DSP at once
making native DSP imitate CAVA
per-TIDAL/Roon DSP
automatic track pre-analysis
phrase/build/drop detection
ML music understanding
new controller implementations
Zone refactoring
mobile work
unrelated backend features
```

Existing DSP techniques and mature libraries should be reused where appropriate, but dependency choices should follow the Audio Feature Contract and measurable requirements.

---

## 21. Architectural invariants

The following are the north-star rules for the audio system:

> **1. Source transport must not define musical semantics.**

> **2. All native analysis consumes one canonical PCM contract.**

> **3. Canonicalization changes technical representation, not musical meaning.**

> **4. Stereo information is preserved until a feature explicitly chooses a channel policy.**

> **5. Audio time is sample-based; polling cadence must not redefine DSP time.**

> **6. Stream discontinuities are data, not music.**

> **7. AudioFeatures have explicit semantic meanings and consumers.**

> **8. One scalar is not “energy” for every use case.**

> **9. CAVA is a retained reference/compatibility backend, not ground truth.**

> **10. Effects and EnergyProfile consume semantic features, not source/backend implementation details.**

> **11. New audio sources should primarily require new adapters, not new analysers.**

> **12. Equivalent music through different source paths should yield equivalent musical interpretation.**

---

## 22. Architectural north star

```text
        TIDAL / Roon / streams
                    AirPlay / LMS / future
                              │
                              ▼
                     SOURCE ADAPTERS
                   decode / receive / time
                              │
                              ▼
                       DECODED PCM
                              │
                              ▼
                    AUDIO CANONICALIZER
                              │
                              ▼
              48 kHz / float32 / stereo
                 sample-timed Analysis PCM
                              │
                              ▼
                   AUDIO FEATURE ENGINE
                  ┌────────┼────────┐
                  ▼        ▼        ▼
              Spectrum  Dynamics  Rhythm
                  └────────┼────────┘
                           ▼
                      AudioFeatures
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
            EnergyProfile          Effects
                 └─────────┬─────────┘
                           ▼
                 Abstract Atmosphere
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
            Hue        Nanoleaf/LIFX   HA / LEDs /
                                      projectors /
                                        future
```

Parallel, during migration:

```text
LMS / supported existing path
              ↓
             CAVA
              ↓
compatibility/reference behavior

NOT ground truth
NOT blocking PCM-first development
possible later deprecation
```

The primary engineering objective is therefore:

> **Build one reliable, observable, source-independent musical-understanding pipeline on canonical PCM, while keeping CAVA operational as a separate compatibility/reference track until evidence supports a later retirement decision.**

This architecture minimizes repeated source-specific DSP work, preserves room for future inputs, and lets HueSync spend its engineering effort on the part that differentiates the product: stable semantic music features and how they drive light and atmosphere.
