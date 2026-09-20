# HueSync — Prior-Art-First Strategy

**Status:** fixed development strategy  
**Date:** 2026-09-14  
**Purpose:** prevent HueSync from reinventing algorithms, DSP methods, MIR techniques, and lighting behavior that already have proven solutions.

---

## 1. Prior-Art-First Strategy

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

---

## 2. Integration with the Elon Musk execution approach

The Prior-Art-First Strategy defines **where solutions should come from**.  
The Elon Musk execution approach defines **how HueSync should test and implement them**.

### Combined development rule

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
