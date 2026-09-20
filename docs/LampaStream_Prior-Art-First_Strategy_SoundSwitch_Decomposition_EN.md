# HueSync — Prior-Art-First Strategy and SoundSwitch Decomposition

**Status:** design/research baseline  
**Date:** 2026-09-13  
**Purpose:** document how HueSync should develop music interpretation without reinventing solutions that already exist.

---

## 1. Fixed development strategy

This is the fixed prior-art gate for algorithmic development in HueSync:

```text
PROBLEM
   ↓
1. What already exists?
   ├─ scientific research
   ├─ Philips / NatLab / universities
   ├─ mature commercial products
   └─ open-source implementations
   ↓
2. Which parts are demonstrably successful?
   ↓
3. How do existing systems implement those principles?
   ↓
4. Which combination fits HueSync?
   ↓
5. What can we simplify / improve?
   ↓
6. Design only the part that is still missing
```

For music interpretation, this means we no longer invent a “HueSync audio-intelligence algorithm” from scratch. We first decompose the proven stack:

```text
Spectrum
→ CAVA / LedFX / WLED / relevant DSP literature

Dynamics / energy
→ established envelope, loudness and activity methods

Onset / transient
→ aubio / Essentia / librosa / madmom etc.

Beat / tempo / phase
→ established beat trackers and tempo estimators

Music state
→ SoundSwitch / Light DJ / Lightjams behavior
  + established MIR techniques

Phrase / structure
→ established segmentation / novelty /
  self-similarity methods and research

Lighting behavior
→ SoundSwitch / Light DJ / LedFX /
  Philips-related knowledge
```

### Design rule

> Analyze proven algorithms, products and research first. Then combine the best building blocks in HueSync. Design something ourselves only when a real gap remains.

This applies before every substantial new DSP, MIR or lighting-algorithm decision.

---

## 2. Elon Musk approach for HueSync

Alongside the prior-art-first strategy, we use a second fixed workflow for execution and debugging: the **Elon Musk approach as agreed for HueSync**.

The point is not “code faster”; it is to aggressively reduce the problem space first and only then accelerate.

```text
1. Question the requirements
   ↓
2. Delete unnecessary parts / steps
   ↓
3. Simplify and optimize
   ↓
4. Accelerate the feedback cycle
   ↓
5. Automate last
```

For HueSync, we translate that into:

```text
Analyze deeply, execute narrowly.

One hypothesis at a time.
One proven boundary at a time.
One minimal change at a time.
One live falsification test immediately afterward.
```

### 2.1 Question the requirements

Before every change, ask:

- Does this problem actually need to be solved now?
- Is the requirement demonstrably necessary for the current phase?
- Is this a product problem, architecture problem, or only a test/measurement problem?
- Does proven prior art formulate the requirement differently?
- Are we trying to fix a downstream symptom while an earlier boundary is still unproven?

Examples for HueSync:

- `bars[]` does not need to represent spectrum, loudness, activity and beat at the same time.
- Phrase detection does not need to be built while Spectrum/Dynamics/Rhythm are not yet independently reliable.
- Do not add a new backend feature unless it is needed to solve an existing desktop or architecture problem.

### 2.2 Delete before adding

Before adding new DSP, abstractions, parameters or state:

- remove obsolete experiments;
- remove duplicate conditioning;
- remove unused compatibility logic;
- remove assumptions that are no longer necessary;
- remove tests that only preserve obsolete behavior;
- avoid source-specific DSP when canonical PCM already exists.

Preferred order:

```text
delete
→ simplify
→ validate
→ only then add
```

Not:

```text
problem
→ new parameter
→ new smoothing
→ new abstraction
→ more tuning
```

### 2.3 Simplify and optimize only after the boundary is proven

Optimize only after we have proven where the failure actually occurs.

When debugging:

```text
input
→ boundary A
→ boundary B
→ boundary C
→ output
```

Find the **first impossible or incorrect transition**.

Examples from the PCM debugging work:

- first prove that bytes actually flow through the FIFO;
- then prove FFT magnitudes are non-zero;
- only then inspect the magnitude→bar boundary;
- do not rewrite the entire analyzer immediately.

### 2.4 Accelerate the feedback cycle

Every minimal change gets the cheapest test that can falsify the hypothesis immediately.

Evidence priority:

```text
1. Live runtime behavior / real measurements
2. The actual code path that explains that behavior
3. A focused reproducing test
4. Unit/integration tests
5. Theory / model analysis
```

A green unit test never overrides a contradictory live observation.

### 2.5 Automate last

Automate only after:

- the behavior is substantively correct;
- the boundary is stable;
- the manual/focused test is proven;
- the contract is clear.

So do not first build a large test harness, abstraction layer or configuration system around an unproven algorithm.

The current acceptance harness **is** allowed because it makes an existing DSP candidate measurable and reproducible without changing its behavior.

### 2.6 Two-strikes rule

When two plausible fixes in a row fail to solve the live problem:

```text
STOP
→ no third guess
→ independent audit / re-analysis
→ determine the first unproven boundary again
```

For HueSync this means:

- ChatGPT guards the problem definition, proven facts and the next boundary;
- Claude Code executes one small change;
- Codex is used as an independent auditor when two targeted fixes fail or when a phase needs to be frozen;
- Claude web / external research is used for prior art and second opinions.

### 2.7 Evidence state per changeset

Every change gets an explicit state:

```text
hypothesis
→ workspace
→ tested
→ committed
→ pushed
→ deployed
→ live validated
```

Never say “fixed” when something only exists in a workspace or has only passed unit tests.

### 2.8 Git and scope discipline

Do not change repository topology without explicit approval:

- no new branches;
- no worktrees;
- no merge/rebase/reset;
- no branch cleanup outside the agreed task.

And for each task:

```text
situation
→ one next action
→ done
```

Do not execute five future implementation steps at once.

### 2.9 Combined development rule

The prior-art-first strategy and the Elon Musk approach work together:

```text
PROBLEM
   ↓
What already exists?
   ↓
Which proven technique fits?
   ↓
What is the first unproven boundary in HueSync?
   ↓
Delete what is unnecessary
   ↓
Make one minimal change
   ↓
Falsify immediately with live data / measurements
   ↓
Freeze what is proven
   ↓
Automate only afterward
```

> **Make it work from first principles first. Then prove it is clean.**

---

## 3. Research question

**Which existing algorithms and techniques are sufficient to explain the publicly observable SoundSwitch behavior?**

This document does **not** claim that SoundSwitch internally uses exactly the algorithms below. SoundSwitch is proprietary. The actual question is:

> Can known, established techniques sufficiently explain the observed product behavior, so HueSync does not need to recreate mysterious proprietary “magic”?

The conclusion of this research is: **yes**.

No publicly visible SoundSwitch behavior was found that requires an unknown or unique algorithm. A combination of classical DSP, Music Information Retrieval (MIR), beat/bar synchronization, structural segmentation and a fixture-aware lighting scheduler is sufficient to plausibly reproduce the observed behavior.

---

## 4. What SoundSwitch publicly and demonstrably does

According to official SoundSwitch documentation:

- AutoScripting analyzes audio files and synchronizes lighting with audio characteristics and changes in the Beatgrid.
- SoundSwitch can import existing Beatgrids from DJ software.
- When no existing script is available, SoundSwitch uses Autoloops that run on the Beatgrid.
- Autoloops use musical lengths of 8, 16, 32, 64 and 128 bars.
- Phrase Detection divides tracks into Intro, Main 1, Main 2, Middle, Bridge and Outro.
- Main 1 is described as higher-energy / chorus-like; Main 2 as verse-like; Bridge as bridge/breakdown-like.
- Phrase boundaries can be snapped to beats or bars.
- Different Autoscript presets can be applied per phrase.
- Fixture categories influence the generated result.
- SoundSwitch includes controlled randomization for Autoscript settings.
- Live audio BPM Detection includes:
  - an audio threshold,
  - a configurable BPM range,
  - recalculation over a configurable time scale,
  - a shorter window for dynamic music and a longer window for stable tempos.
- During silence, the system can pause an Autoloop or go to blackout.

This describes no single “magic” algorithm. It describes a well-organized pipeline of established problem classes.

---

## 5. Sufficient existing building blocks

| Layer | Established technique | Strong references | SoundSwitch-like behavior this explains |
|---|---|---|---|
| Spectrum | STFT + perceptual/log bands + frequency compensation + temporal smoothing | CAVA, WLED Audio Reactive, LedFX | frequency-dependent color/intensity, stable visualization |
| Dynamics | PCM RMS/power, loudness, asymmetric envelope, slow baseline | EBU R128, LARM, Lightjams | quiet/loud, mellow/active, blackout/threshold |
| Onset | spectral flux / SuperFlux + peak picking | librosa/Böck-Widmer, aubio | attacks, kick/snare/hi-hat events |
| Tempo | onset envelope + autocorrelation/tempogram + constrained tempo search | Ellis/librosa, aubio, Essentia | BPM detection |
| Beat | dynamic programming, state tracker/DBN, phase continuity | Ellis/librosa, madmom, aubio | stable beat timestamps |
| Beat phase | beat timestamps + oscillator/PLL/state | classical beat tracking | event exactly on beat |
| Bar clock | beat counter + downbeat/phase state | DJ beatgrid concept | 8/16/32/64/128-bar Autoloops |
| Structure | beat/bar-synchronous chroma + self-similarity/recurrence + novelty/segmentation | Philips Research, MSAF, librosa, CBM | phrase boundaries |
| Section grouping | similarity/clustering of segment features | Philips SVD clustering, spectral clustering/MSAF | repeated verse/chorus-like sections |
| Music state | hysteretic state machine over dynamics, density and rhythm | Light DJ, Lightjams + standard DSP | mellow/building/active/breakdown |
| Lighting scheduler | beat/bar/phrase-quantized preset scheduler + fixture capabilities + bounded randomness | SoundSwitch, Philips/TU/e, Light DJ | a show that feels musically coherent |
| Fallback | beat/bar-synced generative loops | SoundSwitch Autoloops | unknown/live tracks without a full script |

---

## 6. Spectrum: do not reinvent it

The current HueSync V2 spectrum layer uses its own candidate design with log bands, `np.max`, global peak EMA and per-bar falloff. It remains frozen for now as the acceptance baseline.

Relevant prior art shows that mature visualizers **explicitly condition** their spectrum output:

### CAVA

CAVA:
- distributes frequencies over visual bars;
- uses a frequency-dependent EQ that boosts higher frequencies;
- normalizes partly based on bandwidth / number of FFT bins;
- applies smoothing/falloff aimed at visual usefulness.

The CAVA maintainer explicitly describes the display as being made smoother rather than necessarily being an exact audio measurement.

Important for HueSync: this is an established alternative to the ad-hoc `mean → max` choice. The problem “wide high-frequency bands get diluted” can also be addressed through a better definition of band energy plus bandwidth/frequency compensation.

### WLED Audio Reactive

WLED Audio Reactive uses, among other things:
- grouped FFT data;
- averaging in groups (`fftAddAvg`) instead of a simple `max`;
- frequency-response correction;
- gain/AGC;
- squelch/noise handling;
- fast rise and slower decay;
- multiple FFT scaling modes.

Important: WLED does **not** support the earlier claim that `np.max` is the proven WLED method.

### LedFX

LedFX uses mature audio/MIR building blocks and includes:
- pre-emphasis to condition the low↔high balance;
- FFT/phase-vocoder functionality via aubio;
- onset/tempo/beat functionality from the aubio family.

Spectrum conclusion:

> If the current HueSync spectrum candidate fails the acceptance test, do not again choose between `mean`, `max`, `RMS` or a new EMA by intuition. First compare CAVA/WLED/LedFX conditioning on the same PCM input.

---

## 7. Dynamics / energy: independent of spectrum

SoundSwitch has an explicit audio threshold for live BPM/light behavior. Light DJ has a Volume Trigger and distinguishes Mellow from Active based on how active/loud the music is. Lightjams exposes both instantaneous and averaged overall/low/mid/high energy.

This supports one important architecture principle:

> Dynamics/energy must not be derived from already normalized and delayed spectrum bars.

Sufficient existing techniques:

### RMS / power envelope

Frame RMS is the simple absolute foundation:
- source-independent after canonical PCM;
- directly interpretable;
- preserves absolute quiet/loud differences.

### Multi-timescale loudness

EBU R128 provides a proven separation:
- momentary loudness: about 400 ms;
- short-term loudness: about 3 s;
- integrated loudness for longer context.

HueSync does not need to use EBU R128 literally as a show algorithm; it primarily demonstrates that **multiple time scales** for loudness/dynamics are standard practice.

### Asymmetric envelope

Essentia's LARM combines frequency weighting with an asymmetric attack/release envelope; the default documentation mentions a 10 ms attack and 1500 ms release.

For HueSync, the principle matters more than those exact values:
- react quickly to activity;
- fall back more slowly;
- preserve separate absolute level and relative activity.

---

## 8. Onset / transient: a solved problem

A strong established solution is **spectral flux / SuperFlux-like onset detection**.

librosa's `onset_strength` calculates positive spectral changes relative to a filtered reference; the local maximum filtering across frequency comes from Böck & Widmer and is intended to reduce false onset detections caused by vibrato.

This can:
- provide broadband onset strength;
- or be applied per frequency group / multiband.

aubio provides multiple onset methods and beat/tempo detection. HueSync already has onset scaffolding; we do not need to redesign this problem.

---

## 9. Tempo, beat and phase: classical MIR is sufficient

The classic Ellis dynamic-programming beat tracker uses:

1. onset strength;
2. tempo estimation from autocorrelation/onset periodicity;
3. selection of onset peaks consistent with the estimated tempo.

This already explains much of what SoundSwitch needs for live operation.

SoundSwitch also provides public clues that fit this well:
- strong, consistent transients improve BPM detection;
- BPM search range is configurable;
- BPM is recalculated over multiple seconds;
- 5 s suits more dynamic input;
- 10 s provides more stability for fairly constant tempo.

There is therefore no need for a proprietary HueSync BPM formula.

Possible references:
- **librosa/Ellis**: simple, classical, transparent;
- **aubio**: realtime onset/tempo/beat;
- **Essentia**: multiple beat trackers, BPM/ticks/confidence;
- **madmom**: RNN+DBN/HMM, also online-capable, but more complex and with additional model-licensing considerations.

For HueSync:

> Start classical and explainable. Use ML only if a measurable gap remains.

---

## 10. Beatgrid and bar scheduler: probably a large part of the “intelligence”

SoundSwitch imports existing DJ beatgrids when available. This is crucial.

If a reliable Beatgrid exists, SoundSwitch does not need to infer from raw audio every time a lighting change should occur. Much of the behavior then becomes a scheduler problem:

```text
known/detected beat
→ beat phase
→ beat count
→ bar position
→ 8/16/32/... bar cycle
→ effect/color transition
```

A beat/bar-aware scheduler can therefore feel much “smarter” than a more advanced FFT that directly chooses a color every 10 ms.

For HueSync, the priority should become:

1. use external/known timing when it is reliably available;
2. otherwise use live beat tracking;
3. monitor confidence;
4. gracefully fall back to spectrum/dynamics when confidence is low.

---

## 11. Phrase / structure: Philips Research already did this

A Philips Research publication from Eindhoven describes exactly a classical route for segmenting tracks into composition elements such as intro, verse, chorus, bridge and outro:

1. determine beat period and beat phase;
2. calculate beat-synchronous chroma vectors;
3. measure harmonic similarity/contrast with cosine similarity;
4. optimize segment boundaries with dynamic programming;
5. use inter-segment similarity for clustering;
6. use singular-value-decomposition-based clustering to label repeated/contrasting sections.

This can produce abstract structures such as `AABAABAABC`.

This is very important for HueSync:

> The core of SoundSwitch-like phrase detection can already be explained with classical MIR techniques that are decades old — including Philips Research from Eindhoven.

More modern open variants also exist:
- recurrence/self-similarity matrices;
- Foote checkerboard novelty;
- spectral clustering;
- MSAF;
- bar-wise Correlation Block-Matching (CBM).

A modern deep neural network stack is therefore not the necessary first step.

---

## 12. From abstract segments to SoundSwitch-like labels

SoundSwitch exposes the labels:
- Intro
- Main 1
- Main 2
- Middle
- Bridge
- Outro

SoundSwitch does not publish its internal labeling procedure.

But a sufficiently explanatory system can construct these labels from established features:

- **Intro/Outro:** position in track + structural boundary.
- **Main 1:** repeated segment cluster + relatively higher energy; chorus-like.
- **Main 2:** repeated segment cluster + lower/medium energy; verse-like.
- **Middle:** transitional segment, often between verse and high-energy section.
- **Bridge:** structurally contrasting and/or breakdown-like segment.
- **Unknown:** when confidence is too low.

This is a **HueSync design hypothesis**, not a claim about SoundSwitch internals.

More importantly, for good lighting the labels do not have to be musicologically perfect. They only need to be stable enough to select different presets/behaviors at musical boundaries.

---

## 13. Music State: SoundSwitch-like without a phrase detector

For unknown live streams, we can already achieve a lot without full track structure.

Light DJ publicly distinguishes:
- Mellow Effect;
- Active Effect;
- louder/active passages;
- automatic color changes at suitable musical moments;
- separate beat-synced effects.

Lightjams separately exposes:
- spectrum;
- average energy;
- beat power;
- BPM/phase/BAR;
- break;
- build-up/tension;
- drop.

A HueSync Music State Engine can therefore remain relatively thin:

```text
Dynamics + dynamics slope
Onset density
Beat strength/confidence
Spectral density/balance
        ↓
hysteretic state machine
        ↓
MELLOW
BUILDING
ACTIVE
BREAKDOWN
```

This must sit **on top of** separate AudioFeatures, not be mixed into them.

---

## 14. Lighting behavior: the scheduler is as important as the analyzer

SoundSwitch demonstrates that:
- scripts/presets are separate from analysis;
- phrases can receive different presets;
- fixture categories change output;
- transitions can occur on beat/bar boundaries;
- controlled randomization adds variation;
- Autoloops provide fallback behavior.

Philips/TU/e research aligns directly with this. A TU/e thesis about a Philips Lighting music-light system describes lighting as transition patterns with parameters such as color, brightness, saturation and speed; a change point can, for example, be the first beat of a bar. The same research notes that earlier Philips Lighting studies found intrinsic music features such as tempo and key more influential for lighting preference than genre.

Therefore HueSync should ultimately not use:

```text
FFT bin → color
```

as the primary model.

Instead:

```text
AudioFeatures
→ Music State / Structure / Clock
→ Lighting Scheduler
→ Effect + parameters + transition moment
→ Controller
```

---

## 15. Sufficient SoundSwitch-like architecture for HueSync

```text
Any Source
    ↓
Decoded Source PCM
    ↓
AudioCanonicalizer
    ↓
48 kHz float32 stereo Analysis PCM
    │
    ├──────── Spectrum Engine
    │         bars / low / mid / high / balance
    │
    ├──────── Dynamics Engine
    │         level / loudness / activity / energy
    │
    ├──────── Onset Engine
    │         onset / strength / optional multiband onsets
    │
    ├──────── Rhythm Engine
    │         tempo / beat / beat strength / beat phase / confidence
    │
    └──────── Harmonic/Structure Analysis [track-aware, later]
              chroma / recurrence / segment boundaries / clusters
                         │
                         ↓
                  Music State Engine
           mellow / building / active / breakdown
                         │
                         ↓
                    Musical Clock
              beat / bar / phrase position
                         │
                         ↓
                  Lighting Scheduler
       preset/effect selection + bounded randomness
          + beat/bar/phrase-aligned transitions
                         │
                         ↓
              EnergyProfile + Effects
                         │
                         ↓
                    Controllers
```

### Confidence/fallback

```text
structure confident
→ phrase-aware scheduling

else rhythm confident
→ beat/bar-aware generative scheduling

else dynamics reliable
→ mellow/active dynamics-driven lighting

else
→ spectrum/ambient fallback
```

This is more robust than a single analyzer that tries to infer everything at once.

---

## 16. What we explicitly do **not** redesign

Without measurable evidence of a gap, do not redesign:

- FFT;
- onset detection;
- tempo estimation;
- beat tracking;
- beat phase;
- loudness measurement;
- recurrence/self-similarity;
- novelty segmentation;
- structural clustering.

Choose from proven existing techniques first.

What HueSync **does** need to design itself is mainly the **integration**:

- source-independent contracts;
- realtime confidence/fallback;
- Music State mapping;
- EnergyProfile integration;
- controller-/fixture-capability mapping;
- lighting scheduler;
- UX/configuration.

That is where our product value lies.

---

## 17. Licensing / implementation strategy

Not every reference needs to become a literal dependency in HueSync.

Preference:

1. **Permissive implementation available and suitable:** reuse it or evaluate it as a dependency.
2. **Copyleft/AGPL/GPL reference:** study the algorithm and behavior; write our own implementation if license integration is undesirable.
3. **Proprietary product:** use public behavior/documentation as a product benchmark; do not make unsupported claims about internals.

Relevant examples:
- librosa: permissive ISC license.
- MSAF: MIT.
- CAVA: MIT project; check dependency licenses separately.
- WLED: EUPL-1.2.
- LedFX: GPL-3.0.
- aubio: GPL family.
- Essentia: AGPL family for open-source distribution; commercial options exist.
- madmom: source code and bundled models/data have different licensing conditions; assess separately.

---

## 18. Main conclusion

The observed SoundSwitch behavior can be sufficiently explained by an **orchestration of established techniques**:

```text
conditioned spectrum
+ independent dynamics
+ spectral-flux onsets
+ constrained tempo/beat tracking
+ stable beat/bar clock
+ beat-synchronous structural analysis
+ phrase clustering
+ simple music-state semantics
+ fixture-aware preset scheduling
+ musical-boundary transitions
+ controlled variation
+ graceful fallback
```

The observed “intelligence” therefore does not need to come from one exceptional DSP algorithm.

A large part of the product quality most likely comes from:

- reliable timing;
- multiple independent musical features;
- longer musical time scales;
- transitions on beat/bar/phrase boundaries;
- presets/effects that are separate from analysis;
- fallback when higher-level semantics are unreliable.

---

## 19. Next step for HueSync

### Now

The already planned **offline native acceptance harness** remains the next execution step.

Reason:
we first need one reproducible measurement baseline for the current Phase 3 spectrum layer before freezing or replacing it.

No DSP changes during this step.

### Immediately afterward

Once the harness works reproducibly on one real track:

1. evaluate only whether the current spectrum provides sufficient **spectral separation and temporal usefulness**;
2. freeze the spectrum layer if it is good enough; avoid endless tuning for properties that Dynamics/Rhythm will provide separately;
3. then build an **offline prior-art feature prototype** on exactly the same canonical PCM:
   - PCM RMS / dynamics envelope;
   - spectral-flux onset;
   - classical tempo/beat tracker;
   - beat phase/bar clock;
   - only then track-level structure/phrase analysis.

These prototype features are measured and compared first, **not immediately wired into production**.

### First algorithmic implementation after spectrum freeze

The first new production feature should be **Dynamics**, independent of `bars[]`:

```text
canonical PCM
→ absolute frame level
→ fast/slow dynamics envelopes
→ level + activity/energy
```

This directly solves an existing architecture problem: EnergyProfile no longer needs to use `full` from normalized/decaying spectrum bars as musical activity.

Rhythm comes next:

```text
onset envelope
→ tempo
→ beat
→ beat phase
→ bar clock
```

Phrase/structure comes only after that and may begin as track-aware/offline processing.

---

## 20. Sources

### SoundSwitch
- SoundSwitch — AutoScripting Audio Files, Playlists and Crates  
  https://support.soundswitch.com/en/support/solutions/articles/69000847098-soundswitch-autoscripting-audio-files-playlists-and-crates
- SoundSwitch — Phrase Editing  
  https://support.soundswitch.com/en/support/solutions/articles/69000844233-soundswitch-phrase-editing
- SoundSwitch — Autoloops Explained  
  https://support.soundswitch.com/en/support/solutions/articles/69000847100-soundswitch-autoloops-explained
- SoundSwitch — BPM Detection Overview  
  https://support.soundswitch.com/en/support/solutions/articles/69000858486-soundswitch-bpm-detection-overview
- SoundSwitch — Using Beatgrids with SoundSwitch  
  https://support.soundswitch.com/en/support/solutions/articles/69000847586-using-beatgrids-with-soundswitch

### Philips / TU Eindhoven
- G. Geleijnse et al., *Enriching Music with Synchronized Lyrics, Images and Colored Lights*, Philips Research, Eindhoven  
  https://eudl.eu/doi/10.4108/ICST.AMBISYS2008.2873
- Siqi Li, *Implicit Feedback Based Context-Aware Recommender For Music Light System*, Eindhoven University of Technology / Philips Lighting context  
  https://research.tue.nl/files/90854618/master_thesis_final_revised_SiqiLi.pdf

### Open DSP / MIR
- librosa — onset strength / spectral flux  
  https://librosa.org/doc/0.11.0/generated/librosa.onset.onset_strength.html
- librosa — dynamic-programming beat tracker  
  https://librosa.org/doc/0.10.2/generated/librosa.beat.beat_track.html
- Essentia — RhythmExtractor2013  
  https://essentia.upf.edu/reference/std_RhythmExtractor2013.html
- Essentia — loudness and envelope descriptors  
  https://essentia.upf.edu/tutorial_loudness_envelope.html
- Essentia — LARM  
  https://essentia.upf.edu/reference/std_Larm.html
- MSAF — Music Structure Analysis Framework  
  https://github.com/urinieto/msaf
- madmom — beat tracking  
  https://github.com/CPJKU/madmom

### Lighting / visualization references
- CAVA — cavacore  
  https://github.com/karlstav/cava/blob/master/cavacore.c
- WLED Audio Reactive  
  https://github.com/wled/WLED/blob/main/usermods/audioreactive/audio_reactive.cpp
- LedFX / aubio fork  
  https://github.com/LedFx/aubio-ledfx
- Lightjams — audio-reactive lighting  
  https://www.lightjams.com/musicToDMX.html/musicPlayer.html
- Light DJ — Android music visualizer  
  https://lightdjapp.com/android
