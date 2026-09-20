# HueSync DSP Phase 2A — Review Analysis and Recovery Plan

**Status:** Architecture / DSP investigation  
**Source:** Codex independent review of commit `115d9e8`  
**Decision:** Do **not** start Phase 2B yet. Run a bounded Phase 2A correction/control pass first.

---

## 1. Executive conclusion

Codex's review changes the interpretation of Phase 2A substantially.

The experiment was useful, but it did **not** validly characterize real CAVA 0.10.4 quantitatively because the Python `CavaSimulator` materially diverges from the actual CAVA implementation.

The important distinction is:

```text
Phase 2A did not fail completely.

It produced:
- several valid native-HueSync findings,
- one strong structural CAVA/native finding,
- several invalid or unproven CAVA quantitative conclusions.
```

The correct response is therefore **not** to discard the entire experiment and **not** to proceed to Phase 2B.

Instead:

```text
Phase 2A
   ↓
Codex review
   ↓
bounded correction/control
   ↓
freeze proven facts
   ↓
Audio Feature Contract design
   ↓
then decide Phase 2B
```

---

## 2. Findings that survive the review

The following results remain useful and sufficiently supported.

### 2.1 Native opposite-phase cancellation

HueSync native analysis downmixes stereo before FFT:

```text
mono = (L + R) / 2
```

Therefore an exact anti-phase signal:

```text
R = -L
```

cancels before spectral analysis.

Actual CAVA processes left and right channels independently through FFT/magnitude processing before combining their visual bar outputs.

Therefore the structural distinction is real:

```text
native:
L + (-L) → cancellation → no spectral energy

CAVA:
FFT(L), FFT(-L) → equal magnitudes → energy retained
```

This is a **source/stereo semantics difference**, not automatically a bug.

It must later become an explicit HueSync design choice.

---

### 2.2 BandNormaliser steady-state semantics

For an active constant bar with the global gate open:

```text
exertion → 1
clip = 3
output → 1/3
```

This is a confirmed property of the current production `BandNormaliser`.

It does **not** mean CAVA followed by BandNormaliser is simply a constant one-third gain.

BandNormaliser expresses relative exertion; it is not a fixed gain stage.

---

### 2.3 The old “30 Hz is three times slower than 100 Hz” theory is false

The dt-based exponential EMA does not acquire a three-times-longer time constant merely because calls occur at 30 Hz rather than 100 Hz.

The original hypothesis is mathematically disproven.

However, Phase 2A's exact `0.000` comparison was too strong because it compared mostly clipped or settled outputs rather than complete unquantized trajectories.

Correct conclusion:

> The intended continuous-time EMA time constant is cadence-independent for equivalent elapsed time under the same piecewise-constant input assumptions, while sampled/quantized trajectories can still differ.

---

### 2.4 Current narrowband gate behaviour is real

For the tested 440 Hz sine around -6 dBFS peak, the current native global gate can suppress the steady signal because it averages all 30 truncated raw bar values and compares that average with the gate threshold.

This is confirmed production behaviour.

It is **not yet established as a bug**.

It is a HueSync policy/design question that should be revisited only after the desired semantics of spectrum features are defined.

---

### 2.5 Stale CAVA frames can be reprocessed

`CavaPipeline.latest()` can process the same latest frame repeatedly because it has no new-frame/freshness guard.

Therefore stale CAVA bars can be fed through `BandNormaliser` multiple times when producer and consumer cadence diverge.

Phase 2A did not correctly measure the production effect, but the integration risk itself is real.

---

## 3. Findings that must be withdrawn or downgraded

### 3.1 The claimed 19% logarithmic bar-mapping divergence is invalid

The reported high-frequency divergence was caused by the Python simulator's incorrect transcription of CAVA's frequency-edge formula.

The ideal logarithmic edge law in actual CAVA and HueSync native is effectively the same.

Real backend differences still exist because of:

- FFT resolution choices,
- bin truncation versus rounding,
- inclusive/exclusive accumulation,
- collision/transition handling,
- different FFT sizes by frequency region.

So the correct question is no longer:

```text
Do CAVA and native use different logarithmic spacing laws?
```

but:

```text
How do their effective FFT-bin coverage and aggregation differ?
```

---

### 3.2 Quantitative CAVA amplitude conclusions are unproven

The simulator differs from actual CAVA in multiple stateful operations, including:

- FFT selection,
- magnitude scaling,
- equalization,
- per-channel conditioning,
- gravity/falloff,
- autosensitivity ordering,
- silence detection,
- frame-rate handling,
- operational state.

Therefore statements such as:

```text
CAVA steady state ≈ 1.0
```

cannot be treated as validated measurements of real CAVA.

Only the higher-level conclusion survives:

> CAVA's visual-spectrum amplitude semantics and HueSync BandNormaliser's relative-exertion semantics are different.

---

### 3.3 CAVA/native latency numbers are invalid

The experiment assigned incompatible timestamps and confused hop/output periods with availability latency.

Actual latency requires accounting for:

- consumed sample position,
- FFT window duration,
- buffering,
- frame cadence,
- transport/delivery boundaries,
- output availability time.

No production CAVA/native latency comparison has been established.

---

### 3.4 The Python CavaSimulator is not currently a trustworthy CAVA oracle

Passing tests only prove the simulator is internally reproducible.

Zero tests validated it against actual CAVA.

This is a key methodological lesson:

> A transcription of an external DSP implementation must be validated against the external implementation before it can serve as measurement ground truth.

---

## 4. Important architectural lesson

The Codex review reinforces the emerging HueSync architecture rather than weakening it:

```text
canonical PCM
      |
      +-- Spectrum Analysis
      |
      +-- Dynamics Analysis
      |
      +-- Rhythm Analysis
              |
              v
         AudioFeatures
```

A normalized `[0,1]` value is not meaningful merely because it has the same numeric range as another `[0,1]` value.

Feature semantics must be explicit.

Examples:

```text
spectrum bar magnitude
!=
relative spectral exertion
!=
signal level
!=
musical activity
!=
beat strength
```

This supports the plan to stop treating `features.full` or CAVA visual bars as universal "energy".

---

## 5. Recommended recovery strategy

### Phase 2A-R — bounded correction and real-CAVA control

Do **not** build a perfect long-term Python clone of CAVA.

CAVA is now a reference backend, not the future architecture target.

The objective is only to characterize the parts of CAVA that matter for our architectural decisions.

Use the **actual installed CAVA 0.10.4 binary as the authoritative CAVA measurement path**.

The Python simulator may remain as:

- a diagnostic aid,
- a source-level explanatory model,
- or a regression model,

but only after the relevant outputs have been validated against real CAVA.

### 5.1 Correct the diagnostic harness

Correct or remove misleading logic in the existing Phase 2A harness:

- frequency mapping,
- FFT-region selection,
- CAVA input method,
- binary-runner wiring,
- partial-write handling,
- error handling,
- temporal/sample-position accounting,
- per-stage provenance,
- test names that overstate what they validate.

Do not change production DSP.

---

### 5.2 Run a minimal isolated real-CAVA experiment

Never use the production AirPlay FIFO or live LMS SHM.

Use isolated temporary FIFOs/files and the installed `cava` binary.

Use only the minimum deterministic signals needed to validate the important structural questions:

```text
A. 440 Hz amplitude step
B. 440 Hz in-phase stereo
C. 440 Hz opposite-phase stereo
D. ~80 Hz tone
E. ~11 kHz tone
```

These cover:

- gain/conditioning trajectory,
- stereo semantics,
- low-frequency FFT region,
- mid-frequency region,
- high-frequency region,
- effective bar placement.

---

### 5.3 Record explicit provenance

Every result should record:

```text
backend
CAVA version
configuration
sample rate
PCM format
channels
input sample position
input time
output frame index
output availability time
processing stage
bar index
bar value
```

Also save:

- exact CAVA config,
- version/build string,
- input PCM hash,
- generated PCM file,
- raw output bytes,
- machine-readable metrics.

This makes later review repeatable.

---

### 5.4 Compare equivalent stages

Do not compare:

```text
CAVA conditioned visual output
```

directly with:

```text
native post-BandNormaliser relative exertion
```

and call them equivalent.

Use a provenance matrix such as:

| Purpose | CAVA | Native |
|---|---|---|
| spectral placement | pre/post CAVA bar aggregation as observable | native raw bar magnitudes |
| final current production output | CAVA → BandNormaliser | native → BandNormaliser |
| stereo retention | within-backend in-phase/opposite ratio | within-backend in-phase/opposite ratio |
| timing | actual output availability | actual native frame availability |

If no equivalent stage exists, mark the comparison as qualitative rather than forcing a numeric comparison.

---

### 5.5 Improve the BandNormaliser cadence control

Do not spend much more time on this unless needed.

One clean deterministic control is sufficient:

```text
constant → rising step → falling step
```

Record:

- unquantized EMA baseline,
- exertion before byte conversion,
- quantized output.

Compare 30 Hz and 100 Hz at matched elapsed times.

The purpose is only to freeze the conclusion that the old "3x slower" theory is wrong and document where discrete sampling/quantization still differs.

---

### 5.6 Measure stale-frame behaviour separately

Do not combine this with CAVA DSP fidelity.

The stale-frame issue is an integration problem.

Create a focused test that models:

```text
producer publishes frame N
consumer calls latest() multiple times before N+1
```

Measure the resulting BandNormaliser state/output.

No production fix yet.

The output should simply answer:

> What is the measurable consequence of processing one unchanged CAVA frame multiple times?

---

## 6. What not to do

Do not:

- start Phase 2B yet,
- tune the native DSP,
- rewrite BandNormaliser,
- change the gate,
- change stereo downmix,
- remove CAVA from production,
- add beat/BPM algorithms,
- alter EnergyProfile,
- redesign Controllers/Zones,
- attempt a complete CAVA reimplementation.

Those are later decisions.

---

## 7. Exit criteria for corrected Phase 2A

Phase 2A-R is complete when we can state, with real-CAVA evidence:

1. The deterministic PCM fed to real CAVA is known and reproducible.
2. CAVA low/mid/high tone placement is characterized.
3. The opposite-phase structural result is confirmed against the actual binary.
4. CAVA amplitude/conditioning trajectories are measured rather than simulated.
5. Native and CAVA timing axes use explicit sample/output availability semantics.
6. Effective spectral-bin differences are described correctly.
7. The BandNormaliser cadence conclusion is frozen accurately.
8. Stale-frame reprocessing is characterized separately.
9. Every plot/metric identifies its processing stage.
10. No claim is made about EnergyProfile, beat quality or musical activity that was not actually measured.

---

## 8. What comes after Phase 2A-R

After the correction/control pass, the next architectural step should **not automatically be Phase 2B**.

First define:

# HueSync Audio Feature Contract v1

At minimum, explicitly define the semantics required for:

```text
Spectrum
  bars
  low
  mid
  high
  dominant / spectral balance

Dynamics
  level
  peak
  activity

Rhythm
  onset
  onset_strength
  beat
  beat_strength
  phase
  tempo
  confidence
```

For each feature specify:

- meaning,
- range,
- unit if applicable,
- time semantics,
- channel policy,
- normalization policy,
- expected consumers,
- confidence/validity,
- source invariance requirement.

Only then should later experiments decide which algorithms/backends best satisfy that contract.

---

## 9. Relationship to CAVA deprecation

The current evidence strengthens the case for eventually moving toward:

```text
LMS --------+
AirPlay ----+--> canonical PCM --> shared HueSync analysis --> AudioFeatures
Future -----+
```

But no removal decision should be taken from the invalid simulator measurements.

CAVA should currently be treated as:

```text
reference implementation
+
existing production backend
+
behavioral comparison point
```

not as:

```text
ground truth
```

and not necessarily as:

```text
permanent architecture
```

The goal of Phase 2A-R is to learn from CAVA accurately enough that we can later remove or retain specific behaviour intentionally.

---

## 10. Decision

**Recommended next step:**

```text
Phase 2A-R
Correct diagnostic harness
        ↓
Minimal real CAVA 0.10.4 control
        ↓
Repeat only affected comparisons
        ↓
Independent review if conclusions materially change
        ↓
Freeze proven DSP facts
        ↓
Audio Feature Contract v1
```

Only after that should we decide whether a source-equivalence Phase 2B is still the highest-value experiment.

---

## 11. Project record rationale

This analysis should be kept in the repository because it records several important architectural corrections:

- why commit `115d9e8` must not be interpreted as real-CAVA validation,
- which findings remain valid,
- which findings were withdrawn,
- why CAVA is a reference rather than ground truth,
- why feature semantics must be separated,
- why Phase 2B is temporarily deferred,
- and what evidence is required before the project moves on.

This prevents future contributors from rediscovering or accidentally relying on already-invalidated conclusions.
