# HueSync Audio Architecture v1.2

## Audio Feature Contract, Canonical PCM, and Source-Independent Analysis

**Status:** v1.2 — FINAL CONTRACT CANDIDATE — pending GO review  
**Previous version:** v1.1 (pre-implementation review; contains design blockers resolved here)  
**Review outcome:** PCM-first architecture accepted; v1.2 resolves remaining contract blockers  
**Companion doc:** `docs/HueSync_Audio_Architecture_PCM_First_v1.md` (strategic rationale)

---

## 1. Executive Decisions

CAVA characterisation is **closed**. Phase 2A-R validated:

| Signal | Finding |
|--------|---------|
| 440 Hz in-phase, CAVA | mean 12.50 — valid control |
| 440 Hz opposite-phase, CAVA | mean 12.49, ratio ≈ 1.000 — phase preserved |
| 440 Hz in-phase, native | mean raw 2.81 |
| 440 Hz opposite-phase, native | mean raw 0.00 — **complete cancellation** |
| 80 Hz | dominant bar 2 |
| 440 Hz | dominant bar 12 |
| 11025 Hz | dominant bar 29 |
| 19 % bar-mapping divergence claim | WITHDRAWN (formula transcription error) |
| BandNormaliser 30 Hz vs 100 Hz | equal at matched elapsed-time checkpoints |

**The stereo cancellation finding is the single most architecturally important result.**  
Current `(L+R)/2` mono downmix in both source adapters destroys opposite-phase stereo
before the FFT, making native analysis structurally wrong for stereo material.

Administrative decisions:

1. CAVA characterisation is frozen. No further CAVA experiments.
2. Native PCM analysis is the primary track. CAVA is a retained compatibility backend.
3. This document is the authoritative v1.2 design specification.
4. No implementation proceeds without this design being reviewed and approved.

### 1.1 Settled decisions — do not reopen

- 48 kHz, IEEE float32, stereo L/R canonical PCM
- Stereo preserved through canonical boundary
- No canonical AGC, ReplayGain, or loudness normalisation
- Source adapters own transport, decoding, and scaling — not musical semantics
- Native DSP uses sample/audio time (not render-polling time) as dt source
- Missing audio ≠ musical silence; explicit lifecycle events required
- Spectrum, dynamics, transients, and activity are separate semantic domains
- Effects and EnergyProfile consume semantic AudioFeatures
- All buffering and state remain bounded
- Migration is incremental; no phase may intentionally break production
- CAVA is compatibility/reference only; native DSP need not reproduce CAVA numerically
- Beat/tempo/structure/ML remain deferred

---

## 2. Current-State Audit (corrected for v1.2)

### 2.1 Source adapters

| Adapter | Class | Output of `read_new()` | Problem |
|---------|-------|------------------------|---------|
| LMS/Squeezelite | `SqueezeliteShmSource` | mono float32, (L+R)/2 | Destroys stereo |
| AirPlay | `AirPlayPipeSource` | mono float32, (L+R)/2 | Destroys stereo; no resampling |

### 2.2 PcmSource Protocol (current)

```python
class PcmSource(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def read_new(self) -> np.ndarray   # mono float32, [-1.0, +1.0]; empty = no data
    @property
    def sample_rate(self) -> int: ...
    @property
    def running(self) -> bool: ...     # only lifecycle signal; no typed reason
```

### 2.3 BandNormaliser dt source (corrected)

- **`PcmAudioPipeline`**: uses `self._normalise_dt = self._bar_stft.hop / sample_rate`
  (audio time, fixed per sample rate). This is **correct** and **already does not
  use wall-clock dt**. The comment in production code reads:
  `"dt = hop/sample_rate so the time constant is rate-independent (P0 fix)."`
- **`CavaPipeline`**: uses `time.monotonic()` elapsed between `latest()` calls
  (wall-clock / poll cadence). This is an outstanding correctness debt: §19 Phase 8
  must convert CAVA's dt to use approximate audio cadence instead.

The v1.1 claim that native BandNormaliser uses wall-clock dt was incorrect. Only the
CAVA path does.

### 2.4 AudioFeatures (current production)

```python
@dataclass
class AudioFeatures:
    bars: list[float]              # BandNormaliser output [0.0–1.0]
    bass: float                    # _slice_avg(bars, 0.0, 0.20) — cumulative bass range
    mid: float                     # _slice_avg(bars, 0.0, 0.55) — cumulative bass+mid range
    full: float                    # _slice_avg(bars, 0.0, 1.0)
    centroid: float                # normalised bar-index centroid [0.0–1.0]
    onset: bool = False
    onset_strength: float = 0.0    # raw spectral flux (unnormalised, [0,∞))
    onset_bass: bool = False
    onset_mid: bool = False
    onset_treble: bool = False
    onset_bass_strength: float = 0.0
    onset_mid_strength: float = 0.0
    onset_treble_strength: float = 0.0
    beat: bool | None = None       # NOT IMPLEMENTED — always None
    tempo: float | None = None     # NOT IMPLEMENTED — always None
    hpss_active: bool = False
    percussive_energy: float = 0.0
    harmonic_energy: float = 0.0
    sustained_energy: float | None = None
    relative_exertion: float = 0.0  # always equals full
```

**Band boundary facts:**
- `bass` and `mid` use hardcoded bar fractions (0.20 and 0.55 of N), independent
  of `bass_hz`/`mid_hz` profile settings.
- Effects at render time use `_hz_to_frac(profile.bass_hz, ...)` — different
  boundaries (~0.29 and ~0.67 for default 250/2000 Hz with 50–12000 Hz range).
- `mid` is cumulative (covers 0–55%); not an exclusive mid-band.
- `relative_exertion` is always equal to `full`.

### 2.5 Effect consumers (corrected for v1.2)

**`hpss_active` gating — SIX renderers:**

| Effect | `hpss_active` usage |
|--------|---------------------|
| `_PulsesRenderer` | `if hpss_active: target = 0.3 + 0.7 * percussive_energy` |
| `_FlashesRenderer` | `if hpss_active: envelope = 0.3 + 0.7 * percussive_energy` |
| `_FireworksRenderer` | `perc_scale = (0.4 + 0.6 * percussive_energy) if hpss_active else 1.0` |
| `_SwirlRenderer` | `harmonic_energy * full if hpss_active else full` |
| `_WaveRenderer` | `harmonic_energy * full if hpss_active else full` |
| `_SolidRenderer` | `harmonic_energy * full if hpss_active else full` |

**centroid consumers:** `_WaveRenderer` and `_SolidRenderer` (hue drift).  
**`_SpectrumRgbRenderer` and `_SpectrumRgbSpatialRenderer` do NOT consume centroid** —
they use `_hz_to_frac` and `_band_avg` on `features.bars` directly.

**`onset_strength` consumers:** `_FlashesRenderer` does NOT consume `onset_strength`.
It uses `percussive_energy` for HPSS-weighted intensity. `onset_strength` is produced
by both pipelines but is not currently consumed by any rendering effect. It is available
for future use.

### 2.6 EnergyProfile / LayerMixer

```python
# Current production (sync_engine.py):
if features.sustained_energy is not None:
    blend_input = features.sustained_energy
else:
    blend_input = features.full   # degraded fallback; reacts to transients
```

The check is `is not None` (explicit), not truthiness — `sustained_energy = 0.0` would
correctly route through the primary path. AirPlay path never attaches
`SustainedEnergyTracker`; always falls back to `full`.

### 2.7 SustainedEnergyTracker silence behaviour (corrected)

```python
if rms < self._SILENCE_THRESH:   # threshold = 1e-4
    return None if self._short_ema is None else self._value()
```

- **Only audio with `rms < 1e-4`** freezes the tracker (both EMAs unchanged).
- **Ordinary quiet music above 1e-4** continues updating both EMAs normally.
  Under sustained low-amplitude input, short and long EMAs converge; activity tends
  toward ~0.5 (relative context tracks input).
- **First non-silent frame**: both EMAs seed to the observed RMS; `push()` returns
  `0.5` immediately (no extended warmup period).

The v1.1 statement "a quiet intro on a consistent-loudness recording yields activity ≈ 0.5"
was imprecise. The correct statement: a quiet intro above the 1e-4 gate updates both
EMAs; if both EMAs converge before a louder section begins, the contrast registers as a
high relative to the then-established context, not a fixed 0.5 baseline. See §15 and OQ-A.

### 2.8 HPSS median filter parameters (corrected)

`_HPSS_L_P = 31`: this is the **full width** of the frequency-axis sliding median window.
The half-width is `_HPSS_L_P // 2 = 15` bins (bins on each side of centre).

The constant is named `_HPSS_L_P` (suggesting "L half-width" in the paper's notation)
but in code `self._half_p = _HPSS_L_P // 2 = 15`. The source code comment that says
"Frequency-axis median filter half-width in bins. 31 bins" contains a terminology error
in the comment text — 31 is the window width; 15 is the half-width.

HPSS process: magnitude frames from `PcmStft` → time-axis median `H` and
frequency-axis sliding median `P` both on magnitude values → squared to H², P²
for Wiener mask → `mask_h = H²/(H²+P²)`, `mask_p = P²/(H²+P²)` → dot product with
magnitude to get energy fractions. Input domain: magnitude; masks are power-like.

### 2.9 Onset detection domain

All native onset detectors (`StftOnsetPipeline`, `SuperfluxStftPipeline`,
`MultibandOnsetDetector`) operate on **magnitude** frames from `PcmStft.push()`.
Spectral flux = sum of positive magnitude differences per bin. This is magnitude-domain.

Do not describe native onset flux as "power-domain."

### 2.10 SqueezeliteShmSource usage

`SqueezeliteShmSource` is the **primary PCM source** for the LMS-PCM-pipeline path,
not only an optional tap alongside CAVA. It serves two roles:

1. **LMS-CAVA sub-path**: optional parallel PCM tap for HPSS and SustainedEnergyTracker
   (may fail gracefully if SHM is unavailable).
2. **LMS-PCM-pipeline sub-path**: primary input to `PcmAudioPipeline` (always required).

### 2.11 WebSocket consumers

`app.py /ws/preview` sends `sustained_energy` and `relative_exertion`. Both need
updating in Phase 6 consumer cleanup.

### 2.12 Dataflow (corrected)

```
LMS → squeezelite → /dev/shm/squeezelite-{mac}  (stereo S16_LE circular ring)
                             │
              ┌──────────────┴──────────────────────────────────┐
              │                                                 │
       CAVA process (sub-path A)                   SqueezeliteShmSource (sub-path B)
       reads SHM directly via                      Independent parallel reader
       cava.conf: method=shmem                     Used by BOTH:
              │                                    A. optional PCM tap (HPSS+SustainedEnergy)
       raw 8-bit bars → named FIFO                    attached to SyncEngine
              │                                    B. primary source for PcmAudioPipeline
       FifoReader.latest()                              │
              │                                         │
       BandNormaliser (wall-clock dt)        PcmAudioPipeline._run()
              │                             dt = hop/sample_rate (audio time)
       CavaPipeline.latest()               → STFT magnitudes → BandNormaliser bars
              │                            → OnsetDetector (magnitude-domain flux)
              │                            → (if wired: PcmHpss, SustainedEnergyTracker)
              │                                         │
              └──────────────────────┬──────────────────┘
                                     │
                              AudioFeatures
                                     │
                         SyncEngine.run() polls at 30 Hz
                                     │
                              LayerMixer → Scene → HueDriver

AirPlay → shairport-sync → /run/huesync/airplay.pcm  (stereo S16_LE FIFO)
                                     │
                        AirPlayPipeSource.read_new()
                             (L+R)/2 → mono float32
                                     │
                         PcmAudioPipeline (no HPSS, no SustainedEnergyTracker)
                             dt = hop/sample_rate
                                     │
                    AudioFeatures (sustained_energy=None, hpss_active=False)
```

### 2.13 SHM ring buffer size (corrected)

`VIS_BUF_SIZE = 16384`: count of **s16 scalar samples** (interleaved stereo).  
At 2 channels × 2 bytes per sample: 8192 stereo frames ≈ 185 ms at 44100 Hz.

---

## 3. Architectural Invariants

Non-negotiable rules:

1. Source transport must not define musical semantics.
2. All native analysis consumes one canonical PCM contract.
3. Canonicalisation changes technical representation, not musical meaning.
4. Stereo L/R is preserved until a feature extractor explicitly chooses a channel policy.
5. Audio time is sample-based within an epoch. Polling cadence must not redefine DSP time.
6. Stream discontinuities and lifecycle events are explicit typed events, never silent silence.
7. AudioFeatures fields have precise semantic definitions, not implementation references.
8. No single scalar simultaneously represents loudness, spectrum, onset, rhythm, and activity.
9. CAVA is a retained reference/compatibility backend, not ground truth.
10. Effects and EnergyProfile consume semantic features, not source or backend details.
11. New audio sources require new adapters, not new analysers.
12. Equivalent music through different source paths should yield equivalent AudioFeatures within defined tolerances.
13. Feature unavailability is represented by explicit status, not numeric sentinels.
14. No migration phase may intentionally leave production broken awaiting the next phase.
15. Published sample storage is immutable; consumers may retain without copying.

---

## 4. Source Identity and Epoch Model

### 4.1 Definitions

**`source_id`** — Stable logical source identity (e.g. `"lms:aa:bb:cc:dd:ee:ff"`,
`"airplay:/run/huesync/airplay.pcm"`). Does NOT identify one uninterrupted interval.

**`epoch_id`** — Opaque identifier for one uninterrupted, format-consistent playback
interval. Positions are comparable only within the same epoch. Changed on every epoch
boundary.

**`sample_pos`** — First canonical stereo-frame position at 48 kHz **within the current
epoch**. Starts at 0 for every new epoch. Advances only by frames actually emitted.

### 4.2 New epoch required on

- Activation (first connection)
- Restart (source process or transport restarted)
- Reconnect
- Seek
- Source sample-rate change
- Channel-layout change
- Source replacement (where continuity cannot be trusted)
- Confirmed or suspected loss of trustworthy continuity

### 4.3 Epoch boundary actions

All native analysis state resets exactly once per epoch boundary:
resampler state, STFT history, BandNormaliser EMA, onset detector history, HPSS buffer,
activity EMA history.

**One reset per epoch transition.** Do not reset again when the first canonical output
frame is emitted after zero-output initial decoding.

### 4.4 What sample_pos does NOT encode

`sample_pos` is not advanced for unknown missing audio. Unknown loss duration remains
unknown. If the duration of known loss is available as metadata, it may be stored
separately but must not be fabricated into sample_pos continuity.

`source_sample_pos` remains optional provenance in source-native units. For SHM:
`buf_index` is modular, not absolute — use `None`. For the AirPlay pipe: no absolute
position is available.

---

## 5. Lifecycle Event Model

### 5.1 Source read result

The new decoded-source protocol returns a lifecycle-capable typed result. A bare
`(n_samples, 2)` array is not the source protocol.

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Union
import numpy as np

class InvalidationCause(Enum):
    RESTART       = "restart"
    RECONNECT     = "reconnect"
    SEEK          = "seek"
    RATE_CHANGE   = "rate_change"
    FORMAT_CHANGE = "format_change"
    UNKNOWN       = "unknown"

@dataclass(frozen=True)
class DataResult:
    frame: DecodedSourceFrame   # complete, immutable decoded frame

@dataclass(frozen=True)
class TemporarilyNoData:
    pass

@dataclass(frozen=True)
class StreamInvalidated:
    cause: InvalidationCause
    # Known lost duration in source-native samples; None = unknown.
    known_lost_samples: int | None = None

@dataclass(frozen=True)
class EndOfStream:
    pass

# Union that the source protocol returns on each call:
SourceReadResult = Union[DataResult, TemporarilyNoData, StreamInvalidated, EndOfStream]
```

Exact naming may differ if a cleaner typed design fits repository conventions; the
semantics below are binding.

### 5.2 TEMPORARILY_NO_DATA semantics

No audio arrived in this poll interval. Continuity is not known to be broken.

- Do NOT invent silence. Do NOT fill zeros.
- Do NOT advance `sample_pos`.
- Do NOT reset DSP state.
- Do NOT transition epoch.
- Latest feature snapshot remains valid.
- Pending onset events remain in their delivery queue.
- Output hold/fade is an **output policy** applied by Effect or EnergyProfile, not an
  audio-analysis fact.

### 5.3 STREAM_INVALIDATED semantics

Continuity is no longer trustworthy. The current epoch ends.

- Invalidate the current feature snapshot (mark features INVALID — see §13).
- Drop pending onset events for the old epoch.
- Reset all analysis state (see §4.3) — exactly once.
- Next `DataResult` begins a new epoch with a new `epoch_id` and `sample_pos = 0`.

### 5.4 END_OF_STREAM semantics

Explicit clean end.

- The current epoch ends cleanly.
- Old features and onset events must not remain indefinitely active.
- A bounded fade to neutral at the output is acceptable output policy.
- No new epoch begins unless the source reconnects.

### 5.5 Delivered silence vs missing audio

All-zero PCM (`samples == 0.0`) is valid musical silence — a `DataResult`. It advances
`sample_pos`, continues DSP state, and must be handled as real audio.
`TemporarilyNoData` is the absence of any delivery. These two cases must not be
conflated.

---

## 6. Decoded Source PCM Contract

### 6.1 Source adapter responsibilities

Source adapters own:

- Transport reads (SHM mmap, FIFO reads, network reads)
- FIFO/SHM byte handling and circular-buffer arithmetic
- Partial-byte carry between calls (e.g. one leftover byte after an odd read)
- Endian conversion (S16_LE → native integer)
- Integer-to-float32 scaling (divide by 32768.0)
- Construction of **complete channel frames** — no half-samples, no partial stereo frames
- Source lifecycle detection (running state, reconnect detection)

**The source adapter produces `DecodedSourceFrame` objects.** The canonicaliser receives
only complete `DecodedSourceFrame` objects (or lifecycle results). It does not receive
raw bytes, integer PCM, or partial stereo frames.

### 6.2 Channel layout support for v1

| Source layout | Action in source adapter |
|---------------|--------------------------|
| Explicit mono | Deliver mono (1 channel); canonicaliser maps to L=R |
| Explicit stereo L/R | Deliver stereo (2 channels); canonicaliser preserves |
| Unsupported multichannel or unknown layout | Reject explicitly; emit `StreamInvalidated` |

Do not silently use the first two channels of an unknown multichannel stream.

### 6.3 DecodedSourceFrame definition

```python
@dataclass(frozen=True)
class DecodedSourceFrame:
    samples: np.ndarray      # shape (n_frames, channels), dtype=float32
                             # Nominally [-1.0, +1.0]; over-range values are
                             # valid (possible full-scale/source encoding).
                             # WRITEABLE=False on construction.
    sample_rate: int         # native source rate (e.g. 44100, 48000)
    channels: int            # 1=mono, 2=stereo
    source_id: str           # stable logical source identity
    source_sample_pos: int | None  # source-native position; None when unavailable
    over_range: bool         # True when |any sample| >= 1.0 in this frame.
                             # Does NOT imply audible distortion. Full-scale
                             # digital audio is valid; this is diagnostic only.
    wall_ns: int | None      # wall-clock at frame capture (informational only)
```

**Terminology note**: The flag is named `over_range`, not `clipped`. `|sample| >= 1.0`
means the sample reached or exceeded full scale, which may reflect valid pre-emphasis,
mastering, or source encoding — not necessarily audible distortion. Source adapters
must not clamp or repair samples.

**NaN/Inf**: Source adapters must detect non-finite samples and either reject the batch
(emit `StreamInvalidated`) or replace them with 0.0, logging the event. Non-finite
values must never reach persistent DSP state.

### 6.4 Ownership

`DecodedSourceFrame.samples` is read-only after construction (`WRITEABLE=False`).  
The **producer owns stable storage**. Published sample storage must never be overwritten
or reused after the `DataResult` is delivered.  
**Consumers may retain the frame and samples without copying.**  
Internal scratch buffers inside the source adapter may be freely reused for the
*next* frame, but the previously published frame's storage is owned by that frame.

---

## 7. Analysis PCM v1 Contract

### 7.1 AnalysisPcmFrame definition

```python
@dataclass(frozen=True)
class AnalysisPcmFrame:
    samples: np.ndarray        # shape (n_frames, 2), dtype=float32, columns=[L,R]
                               # Nominally [-1.0, +1.0]. WRITEABLE=False.
    sample_pos: int            # First canonical stereo-frame within the current epoch.
                               # Starts at 0 for every new epoch.
    epoch_id: str              # Changes on every epoch boundary.
                               # Do not compare sample_pos from different epoch_ids.
    source_id: str             # Preserved from DecodedSourceFrame
    over_range: bool           # True if any input sample in the canonical window
                               # was over-range (from source) OR if resampler overshoot
                               # produced canonical samples with |value| >= 1.0.
                               # Both causes are aggregated into one flag.

    SAMPLE_RATE: ClassVar[int] = 48000
    CHANNELS: ClassVar[int] = 2
```

**`epoch_id` is the primary mechanism for consumers to detect epoch changes and
reset DSP state.** There is no separate `epoch_event` field on `AnalysisPcmFrame` —
the lifecycle is authoritative through the canonicaliser's `CanonicalReadResult` (§9.2).

### 7.2 Fixed parameters

| Parameter | Value |
|-----------|-------|
| Sample rate | 48,000 Hz |
| Format | float32, WRITEABLE=False |
| Channels | 2 (stereo) |
| Amplitude | nominally [-1.0, +1.0]; over-range preserved as data |
| Time base | `sample_pos / 48000` seconds within epoch |

### 7.3 Authoritative time within an epoch

Audio time = `sample_pos / 48000`.  
Wall-clock is informational only (diagnostics, latency logging). DSP must not use
wall-clock differences as dt for EMA filters when sample-accurate timing is available.

`sample_pos` records signal time, not processing availability time. Resampler group
delay (~1–3 ms for 44100→48000 Hz) is processing latency — it shifts when results
become available, not what signal time they represent.

### 7.4 Ownership

Same rule as §6.4: **the producer (canonicaliser) owns stable storage.**  
Published frames may be retained by consumers without copying.  
Scratch buffers inside the canonicaliser may be reused for the next frame.  
`epoch_id`, `source_id`, `sample_pos`, `over_range` are immutable value types.

---

## 8. Ownership Contract (authoritative)

This section is authoritative. §6.4 and §7.4 apply the same rule to both frame types.
There are no exceptions.

### 8.1 Published frame ownership

For both `DecodedSourceFrame` and `AnalysisPcmFrame`:

- A published frame owns stable sample storage.
- The **producer must never overwrite or reuse published storage** after delivery.
- **Consumers may retain a frame and access its samples without copying.**
- Published `samples` arrays are read-only (`WRITEABLE=False`).
- No producer-owned writable alias may subsequently mutate published storage.
- Internal scratch/accumulation buffers may be reused — they must not be the same
  memory as a published frame's `samples`.

### 8.2 AudioFeatures immutability

Published `AudioFeatures` instances are not mutated after delivery.  
**Current violation**: the CAVA sub-path in `SyncEngine.run()` mutates a `features`
object after initial creation (adding HPSS and `sustained_energy` from the SHM tap).
This must be corrected during migration — produce a single complete `AudioFeatures`
instance rather than mutating a shared one.

### 8.3 Scope

Do not introduce leases, refcounts, pooled ownership, or zero-copy complexity in v1.
Copy-on-need is acceptable for consumers that want to aggregate data across multiple
frames. The ownership rule only removes the obligation to copy for basic retention.

---

## 9. Canonicaliser and Resampler Contract

### 9.1 Canonicaliser responsibilities

**Receives:** `DataResult` (containing a complete `DecodedSourceFrame`) or lifecycle
results (`StreamInvalidated`, `EndOfStream`, `TemporarilyNoData`).  
**Never receives:** raw bytes, integer PCM, or partial stereo frames.

**Owns:**
- Mono → stereo duplication (L=R)
- Stereo L/R preservation
- Other-rate → 48 kHz resampling
- Epoch assignment and `epoch_id` generation
- Canonical `sample_pos` tracking
- Canonical `over_range` aggregation (source flag OR resampler overshoot)
- Canonical lifecycle propagation

**Does not own:**
- Byte handling, endian conversion, integer decoding (source adapter)
- Loudness normalisation, AGC, ReplayGain
- Spectral analysis, onset detection, beat detection

Internal buffering inside the canonicaliser is described as:
- Decoded-frame buffering (accumulating partial canonical output from the resampler)
- Resampler state (filter history)

Not as byte/sub-frame reconstruction.

### 9.2 Canonical read result

The canonicaliser returns a typed result analogous to `SourceReadResult`:

```python
CanonicalReadResult = Union[CanonicalData, TemporarilyNoData, StreamInvalidated, EndOfStream]

@dataclass(frozen=True)
class CanonicalData:
    frame: AnalysisPcmFrame   # complete, immutable canonical frame
```

`epoch_id` on `AnalysisPcmFrame` is the reset authority for DSP consumers. Consumers
detect epoch change by comparing `epoch_id` to the previous frame's `epoch_id`.

### 9.3 Resampler contract

**Library selection**: moved to Phase 2 implementation (not Phase 3). Recommended:
`soxr` Python package (wraps libsoxr). Alternative: `scipy.signal.resample_poly`.
The Phase 2 implementation must commit to one library and document:
- Its streaming/stateful interface
- Group-delay compensation offset
- Flush behaviour on `END_OF_STREAM`

**Stateful across arbitrary input chunks**: chunk boundaries in the source adapter
must not alter the canonical timeline.

**sample_pos from actual output**: per-input-chunk sample counts must not be rounded
independently. Rounding error must be accumulated and corrected across chunks so that
`sample_pos` matches actual emitted frames exactly.

**Resampler overshoot**: resampling may produce canonical samples with `|value| > 1.0`
even if all source samples were in range. Set `over_range = True` in such cases.
Do not silently clamp canonical samples.

### 9.4 Epoch/resampler event ordering

**A. STREAM_INVALIDATED:**

1. Emit `StreamInvalidated` for the old epoch.
2. Mark old epoch ended.
3. Discard old resampler/filter history (do not drain).
4. Reset downstream DSP **exactly once** for this epoch transition.
5. Next `DataResult` creates a new `epoch_id` and `sample_pos=0`.
6. If the first decoded input produces **zero canonical output samples**, the new epoch
   identity is pending — attach it to the first canonical frame actually emitted.
7. Do NOT reset again when that first frame is emitted. One reset per epoch transition.

**B. CLEAN END_OF_STREAM:**

1. No new decoded input follows for the current epoch.
2. The canonicaliser MAY drain valid resampler output (group delay tail) attributable
   to the final source samples per the selected library's defined flush semantics.
3. All drained `CanonicalData` frames are emitted BEFORE `EndOfStream`.
4. `EndOfStream` is emitted exactly once after the last canonical data.
5. Do not drain arbitrary zero-padding; only real filter tail counts.
6. Downstream consumers may then fade output according to policy.

**C. TEMPORARILY_NO_DATA:**

Pass through unchanged. No resampler flush. No sample_pos advance. No epoch transition.
No DSP reset.

**D. NEW EPOCH DATA (reconnect/seek/rate-change):**

The source adapter signals the event through `StreamInvalidated` BEFORE delivering the
new audio as a subsequent `DataResult`. The canonicaliser does not need to infer epoch
transitions from frame metadata — the lifecycle event type is authoritative.

There must be **one reset per epoch transition**. Do not encode the same transition
as both a `StreamInvalidated` result and a redundant frame-level marker that triggers
a second reset.

### 9.5 source_sample_pos provenance

`source_sample_pos` from `DecodedSourceFrame` is preserved in canonicaliser diagnostic
metadata. It is NOT included in `AnalysisPcmFrame` as a public contract field; it is
implementation detail of the canonicaliser's internal state. If a consumer needs this
for diagnostics, provide a separate diagnostic API.

---

## 10. Channel Policy

### 10.1 Motivation

Phase 2A-R proved one qualitative result: CAVA retains opposite-phase stereo energy
(ratio ≈ 1.000); native `(L+R)/2` cancels it completely (ratio = 0.000).

The power-mean policy below prevents phase cancellation. **Do not claim it is
numerically equivalent to CAVA.** The experiment established energy preservation;
it did not fully characterise the two pipelines' quantitative relationship.

### 10.2 Policy table

| Feature | Policy | Formula |
|---------|---------|---------|
| Spectrum bars | RMS-like per-bin magnitude combination | `M[k] = √((|FFT(L)[k]|² + |FFT(R)[k]|²) / 2)` |
| bass, mid, high, full | Derived from bars | Mean of bar subsets |
| centroid | Derived from bars | Bar-index centroid |
| level (RMS) | Phase-safe RMS combination | `√((RMS(L)² + RMS(R)²) / 2)` |
| activity | Input: level (above) | Temporal smoothing on phase-safe amplitude |
| onset (wideband) | Spectral flux on combined magnitude | `flux(M[k])` as defined above |
| onset per band | Per-band magnitude flux | Sub-band M[k] |
| percussive/harmonic | HPSS on combined magnitude M[k] | Median filter on magnitude; masks on squared magnitude |

**Notes:**
- `M[k] = √((|L|² + |R|²) / 2)` is an RMS-like spectral **magnitude** combination,
  not power. Do not call spectrum/HPSS operations "power-domain."
- Level is computed in the time domain — this is correct and does not require deferring
  channel combination until after FFT.
- Onset spectral flux operates on magnitude differences (see §2.9).
- Stereo spatial information is carried by both phase and level differences between L
  and R. The policy above collapses to mono for analysis; future spatial features must
  use L and R independently. Deferred to a future phase.

---

## 11. Audio Feature Semantic Contract

### 11.1 Guiding principle

Every field admitted to this contract must:
- Have one precise semantic meaning independent of source or backend
- Have a defined validity (§13) and update cadence relative to audio time
- Have a defined epoch-reset behaviour
- Serve a concrete lighting use case

### 11.2 SpectrumLayout (required before Phase 4)

Before Phase 4 can freeze AudioFeatures spectrum data, a layout identity must be
defined. Equivalent audio with equivalent `SpectrumLayout` produces equivalent
spectrum features; different Analyser configurations may produce different bar values.

```python
@dataclass(frozen=True)
class SpectrumLayout:
    bar_count: int               # number of log-spaced bars (default 30)
    lower_cutoff_hz: float       # lowest frequency (default 50.0 Hz)
    upper_cutoff_hz: float       # highest frequency (default 12000.0 Hz)
    bass_boundary_hz: float      # bass/mid divider (default 250.0 Hz)
    mid_boundary_hz: float       # mid/high divider (default 2000.0 Hz)
    # Log-linear mapping: bar i covers [10^(lo + i/N*(hi-lo)), 10^(lo + (i+1)/N*(hi-lo))]
    # where lo = log10(lower_cutoff_hz), hi = log10(upper_cutoff_hz).

    def hz_to_bar_frac(self, hz: float) -> float:
        """Log-fraction of hz within [lower_cutoff_hz, upper_cutoff_hz]."""
        ...

    def bass_bar_index(self) -> int:
        """Exclusive upper bar index for the bass band. Rounding: round()."""
        ...

    def mid_bar_index(self) -> int:
        """Exclusive upper bar index for the mid band."""
        ...
```

Bar-index boundary: `round(hz_to_bar_frac(boundary_hz) * bar_count)`.  
Empty-band behaviour: return 0.0.  
Edge inclusivity: `[bar_lo, bar_hi)` — lower inclusive, upper exclusive.

### 11.3 Centroid definition

`centroid` is a **normalised bar-index centroid**:

```
centroid = (Σ_i  i * bars[i]) / (Σ_i  bars[i]) / (N - 1)
```

where `N = len(bars)` and division by `(N - 1)` maps the result to [0, 1].

- 0.0 = energy concentrated in bar index 0 (lowest frequency)
- 1.0 = energy concentrated in bar index N-1 (highest frequency)
- Denominator for N=1: define `centroid = 0.0`.
- Centroid is NOT physical Hz. Do not describe it as "frequency-weighted."

### 11.4 Contract fields

```python
@dataclass
class AudioFeatures:
    # ── Timing ────────────────────────────────────────────────────────────────
    epoch_id: str
    # Identifies the epoch that produced this snapshot.
    # Consumers detect epoch change by comparing to previous epoch_id.

    support_start_sample: int
    support_end_sample: int   # exclusive
    # The canonical 48 kHz sample range [start, end) corresponding to the
    # CURRENT analysis window that produced this snapshot.
    # Audio time of window centre: (start + end) / 2 / 48000 s.
    # These describe the current window, NOT the complete causal history
    # of stateful features. Activity depends on tens of seconds of prior
    # history; HPSS depends on its rolling buffer; BandNormaliser on its EMA.
    # Support interval is a timing anchor, not a causal-history claim.

    # ── Spectrum ──────────────────────────────────────────────────────────────
    bars: list[float]
    # N log-spaced frequency bands per SpectrumLayout.
    # Semantic: per-band relative spectral activation.
    # Range: [0.0, 1.0] after BandNormaliser conditioning.
    # OQ-C: exact 0.0/typical/1.0 anchors not yet calibrated (see §23).

    bass: float
    # Mean bars activation for bars in [0, bass_bar_index).
    # Exclusive bass band (not cumulative). Range: [0.0, 1.0].
    # NOTE: this definition differs from current production (currently cumulative
    # 0–20%). Phase 4 must audit all bass consumers before change.

    mid: float
    # Mean bars activation for bars in [bass_bar_index, mid_bar_index).
    # Exclusive mid band. Range: [0.0, 1.0].
    # NOTE: differs from current production (currently cumulative 0–55%).

    high: float
    # Mean bars activation for bars in [mid_bar_index, bar_count).
    # NEW in v1. Range: [0.0, 1.0].

    full: float
    # Mean activation over all bars. Retained for backward compatibility.
    # Range: [0.0, 1.0].

    centroid: float
    # Normalised bar-index centroid (see §11.3). Range: [0.0, 1.0].

    # ── Dynamics ──────────────────────────────────────────────────────────────
    level: float
    # Phase-safe amplitude metric: √((RMS(L)² + RMS(R)²) / 2) over current window.
    # An amplitude metric, not "instantaneous signal power."
    # NOT conditioned (no EMA, no AGC). Range: [0.0, 1.0] (clamped).
    # NEW in v1.

    # ── Activity ──────────────────────────────────────────────────────────────
    activity_status: FeatureStatus
    activity: float | None
    # Sustained musical intensity for EnergyProfile blending.
    # Valid only when activity_status == VALID. None otherwise.
    # Range when VALID: [0.0, 1.0].
    # See §15 for full semantics and candidate implementation.

    # ── Onset / Transient ─────────────────────────────────────────────────────
    onset: bool
    # Compatibility/diagnostic projection of the OnsetEvent queue.
    # True if one or more onset events were generated since the previous snapshot.
    # Effects requiring reliable transient delivery must consume the
    # OnsetEvent queue (§14), not only this field.

    onset_strength: float
    # Calibrated transient salience [0.0, 1.0].
    # Requires normalisation (see §12.4). Currently raw flux; migration needed.
    # 0.0 when no onset; calibrated 1.0 = strongest in reference set.

    onset_bass: bool
    onset_mid: bool
    onset_treble: bool
    # Per-band onset projections (valid when onset_method ∈ {multiband, combined}).

    onset_bass_strength: float
    onset_mid_strength: float
    onset_treble_strength: float
    # Per-band calibrated salience [0.0, 1.0].

    # ── HPSS ──────────────────────────────────────────────────────────────────
    hpss_status: FeatureStatus
    percussive_energy: float | None
    harmonic_energy: float | None
    # Percussive and harmonic energy fractions.
    # Values present only when hpss_status == VALID.
    # When VALID: percussive_energy + harmonic_energy ≈ 1.0.
    # When UNAVAILABLE/DISABLED: both are None (NOT 0.5/0.5).
    # Consumers must check hpss_status before using these values.
```

### 11.5 Fields removed from v1

| Field | Reason |
|-------|--------|
| `relative_exertion` | Alias for `full`; removed |
| `beat` | Unimplemented; deferred |
| `tempo` | Unimplemented; deferred |
| `hpss_active` | Implementation detail; replaced by `hpss_status` |
| `sustained_energy` | Renamed `activity`; explicit status field added |
| `frame_sample_pos` | Replaced by `epoch_id` + `support_start/end_sample` |

### 11.6 Fields added in v1

| Field | Why |
|-------|-----|
| `epoch_id` | Epoch-change detection for DSP consumers |
| `support_start_sample`, `support_end_sample` | Audio-time anchor |
| `high` | Completes bass/mid/high triad |
| `level` | Phase-safe amplitude metric; activity input |
| `activity_status`, `activity` | Explicit status/value; replaces `sustained_energy` |
| `hpss_status` | Explicit status; removes numeric sentinel |

### 11.7 CAVA compatibility timing

Native `AudioFeatures` carries authoritative `epoch_id`, `support_start_sample`,
`support_end_sample` derived from canonical 48 kHz sample positions.

CAVA does not provide sample-position authority. A CAVA-produced snapshot carries:
- `epoch_id`: opaque identifier, changed when CAVA is restarted
- `approximate_wall_ns`: wall-clock time of the FIFO delivery (not sample time)
- `timing_quality`: a flag (e.g. `APPROXIMATE`) distinguishing approximate-wall-clock
  from native-sample timing
- `support_start_sample = 0`, `support_end_sample = 0` (or omitted/sentinel to
  indicate "not applicable")
- `activity_status`, `hpss_status`: `UNAVAILABLE` unless the SHM tap is wired

Do NOT synthesise `support_start_sample` from CAVA frame counts. Do not weaken native
sample-position guarantees to fit CAVA.

If one `AudioFeatures` type cannot honestly represent both native and CAVA timing
without fake values, define a minimal wrapper or variant for the CAVA path. Keep it
small; CAVA is compatibility-only.

---

## 12. Native-v1 DSP Implementation Profile

This section describes implementation details that inform v1 but are not the semantic
contract. The semantic contract (§11) must not freeze these coefficients.

### 12.1 STFT

- Hamming window, 2048 samples
- Hop = `round(sample_rate * 0.010)` ≈ 10 ms (480 samples at 48 kHz)
- At 48 kHz: window ≈ 42.7 ms; frame rate ≈ 100 Hz
- Output: 1025-bin magnitude spectrum per frame (rfft of 2048-sample window)

Window length (2048) and hop (480) are distinct. Do not conflate them.

### 12.2 BandNormaliser

- Per-bar asymmetric EMA: attack τ ≈ 5 ms, release τ ≈ 700 ms
- `exertion_clip = 3.0`: clips to 3× rolling average before 0–255 scaling
- `dt` = `hop / sample_rate` for `PcmAudioPipeline` (audio time, correct)
- `dt` = wall-clock elapsed for `CavaPipeline` (approximate; migration debt → Phase 8)
- State resets on epoch boundary

These coefficients are a candidate native-v1 profile, not the semantic anchor for bars.

### 12.3 Band definitions (corrected)

**v1 target**: bass/mid/high boundaries derived from `SpectrumLayout.bass_boundary_hz`
and `SpectrumLayout.mid_boundary_hz` via `round(hz_to_bar_frac(hz) * N)`.

With defaults (lower=50, upper=12000, bass=250, mid=2000 Hz):
- bass boundary ≈ bar index 9 (≈ 29% of 30 bars)
- mid boundary ≈ bar index 20 (≈ 67% of 30 bars)

**Current production (both CavaPipeline and PcmAudioPipeline) uses hardcoded 0.20/0.55
fractions**, not Hz-based boundaries. This is a factual discrepancy from v1 target; it
is a behaviour change in Phase 4. Effects at render time use `_hz_to_frac` which matches
the v1 Hz-based definition, not the 0.20/0.55 AudioFeatures field definition.

Phase 4 must audit all consumers of `bass`, `mid` before changing their definitions.

### 12.4 Onset detector

- Wideband: Dixon (2006) peak-picking on spectral flux computed from magnitude values
- Spectral flux = sum of positive magnitude differences per bin (magnitude domain)
- Superflux: Böck & Widmer (2013) max-filtered magnitude flux
- Per-band (multiband): separate flux per band of magnitude spectrum

**onset_strength normalisation**: raw magnitude flux `[0, ∞)` is not a stable public
semantic value. v1 must normalise to [0.0, 1.0] before publication. Method (running
max, fixed reference) requires real-music validation. Phase 4 must either deliver
normalised `onset_strength` or retain it as provisional implementation-profile
semantics (with OQ-C covering calibration, since onset_strength anchors share the
same validation question as bars).

### 12.5 HPSS (native-v1 candidate)

- Input: magnitude frames M[k] from `PcmStft`
- Time-axis rolling buffer: `_HPSS_L_H = 17` frames (≈ 170 ms at 100 Hz)
- Frequency-axis sliding median: window width = 31 bins; half-width = 15 bins
  (`_HPSS_L_P = 31`; `half_p = _HPSS_L_P // 2 = 15`)
- Harmonic mask: `H² / (H² + P²)` where H = time-axis median, P = frequency-axis median
- Percussive mask: `P² / (H² + P²)` — masks are computed from squared magnitudes
- Output: energy fractions in [0, 1]; sum ≈ 1.0
- Warmup: `hpss_status = WARMING_UP` for first `_HPSS_L_H // 2` frames (≈ 85 ms)

### 12.6 Activity candidate

See §15. Candidate: `SustainedEnergyTracker` with amplitude-ratio formula. Parameters
(τ values, dB range) are not part of the semantic contract.

---

## 13. Feature Validity Status

### 13.1 Status enum

```python
class FeatureStatus(Enum):
    VALID        = "valid"       # computed and meaningful
    WARMING_UP   = "warming_up" # running but insufficient history
    UNAVAILABLE  = "unavailable" # path not wired or source not connected
    DISABLED     = "disabled"    # deliberately disabled by configuration
    INVALID      = "invalid"     # unusable result or epoch-invalidated
```

### 13.2 Which features need explicit status

Explicit `FeatureStatus` fields are required only for **optional feature families**
whose availability varies independently per path:

- `activity_status` / `activity`
- `hpss_status` / `percussive_energy` / `harmonic_energy`
- Future optional families

**Bars, bass, mid, high, full, centroid, level, onset, onset_strength** do not each need
their own status field. They are present and valid on every `AudioFeatures` snapshot
produced by a `CanonicalData`-derived pipeline frame. Their status is implied by the
snapshot's existence.

### 13.3 Snapshot lifecycle

A `AudioFeatures` snapshot is valid from the moment it is published until:
- `StreamInvalidated` is received (mark INVALID — consumers must not use old snapshot)
- `EndOfStream` is received (transition to neutral output)
- A new snapshot supersedes it (normal 100 Hz production)

### 13.4 Per-family status

| Feature family | Status on path not wired | Status after epoch boundary | Status at warmup |
|----------------|-------------------------|-----------------------------|-----------------|
| bars/etc | N/A — implied valid | implies new snapshot | BandNormaliser EMA transient is still VALID data |
| activity | UNAVAILABLE | INVALID until re-initialised | WARMING_UP (brief; first non-silent → 0.5) |
| HPSS | UNAVAILABLE / DISABLED | INVALID then WARMING_UP | WARMING_UP (≈85 ms) |

### 13.5 Output policy during non-VALID

Effects and EnergyProfile apply bounded deterministic output policies. See §16.

---

## 14. Feature and Event Timing

### 14.1 Continuous feature timing

Every `AudioFeatures` snapshot carries `epoch_id`, `support_start_sample`,
`support_end_sample` describing the current analysis window. Continuous features
produced from the same STFT frame share one support interval.

`support_start/end_sample` describe the **current window**, not the causal history
of stateful features (activity may reflect 30 s of prior history; HPSS reflects 170 ms).

### 14.2 OnsetEvent — authoritative transient delivery

Onset is an event, not only a continuous field. The analyser runs at ~100 Hz; the
renderer polls at ~30 Hz. A snapshot-only design causes events to be missed.

**The OnsetEvent queue is the authoritative delivery mechanism for transient events.**

```python
@dataclass(frozen=True)
class OnsetEvent:
    epoch_id: str
    event_sample_pos: int    # estimated signal time within epoch, at 48 kHz
                             # Delayed by up to W hops (Dixon peak-picker look-ahead)
                             # relative to the physical transient.
    strength: float          # calibrated salience [0.0, 1.0]
    bands: frozenset[str]    # e.g. frozenset({"bass", "mid"}) for multiband
```

`event_sample_pos` is the estimated signal time of the transient, which may lag the
physical event by up to W hops (~30 ms at 100 Hz, W=3) due to the local-max window.
Do not require publication "in the frame that contains it."

### 14.3 Queue behaviour

- Bounded ring; recommend capacity ≥ 32 events (configurable).
- **Overflow policy: drop OLDEST unconsumed event.** Record a diagnostic counter.
- Deduplication: events with the same `epoch_id + event_sample_pos` are one event;
  do not emit duplicates.
- Per-band detections at the same `event_sample_pos` are merged into one event's
  `bands` set where appropriate.

### 14.4 Snapshot onset fields

`onset`, `onset_bass`, etc. on `AudioFeatures` are **compatibility and diagnostic
projections** of the OnsetEvent queue. They indicate whether any onset event was
generated in the window corresponding to this snapshot.

Effects requiring reliable transient triggering must consume events from the queue.
Effects that only need the snapshot field (e.g. `_FlashesRenderer` which polls
`features.onset`) may continue to do so during the migration period; the event queue
is not mandatory for all consumers in v1.

---

## 15. Activity Semantics

### 15.1 Semantic requirement (settled)

`activity` is a dimensionless estimate of **sustained musical intensity relative to
the recent musical context**, suitable for EnergyProfile blending on a timescale of
seconds to tens of seconds.

This semantic target is settled. The algorithm that computes it is **not settled** —
the current implementation is a candidate requiring real-music validation.

### 15.2 What activity IS NOT

| Not this | Why |
|----------|-----|
| Instantaneous RMS | Too fast; single-window amplitude |
| FFT maximum | Frequency-specific |
| CAVA autosens | Backend-specific |
| `full` (relative exertion) | Reacts to individual transients |
| Absolute mastering loudness | Context-independent |

### 15.3 Candidate native-v1 implementation

`SustainedEnergyTracker` (current production):

```python
# Input corrected for v1: phase-safe level = √((RMS(L)² + RMS(R)²) / 2)
# (current production uses mono input; phase-safe input is the v1 target)

# Gate: if rms < 1e-4, NEITHER EMA is updated — state freezes.
#        This prevents false HIGH on resume after exact/near-silence.
#        Only audio below 1e-4 gates; ordinary quiet audio above this threshold
#        continues updating both EMAs normally.

short_ema += alpha_short * (rms - short_ema)  # τ = 300 ms
long_ema  += alpha_long  * (rms - long_ema)   # τ = 30 s

# 20*log10 is correct here: input is amplitude (RMS), not power.
rel_db = 20 * log10(short_ema / long_ema)
activity = clamp((rel_db + 6) / 12, 0.0, 1.0)  # ±6 dB → [0, 1]
```

**Accurate silence behaviour:**

- Only `rms < 1e-4` freezes the tracker. This threshold is much lower than ordinary
  quiet music; most real quiet passages are above it.
- **Ordinary quiet music above 1e-4 continues updating both EMAs normally.**
  Under sustained low-amplitude input, short_ema and long_ema converge; activity
  tends toward ~0.5 (context-relative neutrality).
- First non-silent initialisation: both EMAs seed to first observed RMS; returns
  0.5 immediately (no extended warmup period before first value).

Parameters (τ_short, τ_long, range_db) are candidates, not settled semantic contract.

### 15.4 Open product decision OQ-A (do not resolve here)

**Should sustained low-intensity musical material remain semantically LOW activity,
or should it adapt toward context-neutral (~0.5) over time?**

Correct framing (corrected from v1.1):

- Under the candidate algorithm, sustained quiet music ABOVE the 1e-4 gate continues
  updating both EMAs. Eventually short_ema ≈ long_ema and activity ≈ 0.5 (relative
  context neutrality).
- The gate-below-1e-4 freeze prevents a very-long-silence artefact, not ordinary
  quiet music.
- The product question is: is relative-context neutralisation (the existing behaviour
  for ordinary quiet) the right product semantic, or should quiet passages maintain
  "LOW" activity regardless of how long they last?

**BLOCKED ON PRODUCT DECISION.** Must resolve before Phase 7.

### 15.5 Status reporting

| Situation | `activity_status` | `activity` |
|-----------|------------------|-----------|
| First non-silent frame | VALID | 0.5 |
| Normal audio | VALID | [0.0, 1.0] |
| Audio below 1e-4 gate | VALID (frozen at last value) | last valid |
| After epoch boundary, before new audio | INVALID | None |
| Path not wired to tracker | UNAVAILABLE | None |

---

## 16. EnergyProfile and Fallback Policy

### 16.1 Activity may be non-VALID

`EnergyProfile` must define deterministic bounded behaviour for all activity statuses.
Activity must not be assumed to become permanently mandatory.

### 16.2 Explicit status checks required

Never:

```python
blend_input = activity or full   # WRONG: activity=0.0 is falsy but valid
```

Always:

```python
if activity_status == FeatureStatus.VALID:
    blend_input = activity
elif activity_status == FeatureStatus.WARMING_UP:
    blend_input = <warmup policy>
else:  # UNAVAILABLE, INVALID
    blend_input = <fallback policy>
```

### 16.3 Candidate fallback policies (OQ-B pending)

| Status | Candidate policy |
|--------|-----------------|
| VALID | Use activity |
| WARMING_UP | Hold 0.5 (neutral) or use `full` temporarily |
| UNAVAILABLE | Use `full` as degraded fallback (acceptable during Phases 1–5) |
| INVALID (post-epoch) | Hold last valid briefly; then return to neutral |

### 16.4 Output policy during stream events

| Event | Recommended output policy |
|-------|--------------------------|
| TEMPORARILY_NO_DATA | Hold last blend value; bounded duration |
| STREAM_INVALIDATED | Transition to neutral over bounded time |
| END_OF_STREAM | Fade to neutral |

These are output policies, not audio analysis facts. The Effect layer implements them.

### 16.5 Open product decision OQ-B (do not resolve here)

**What is the final EnergyProfile output blend when activity is UNAVAILABLE or INVALID?**

`full` as a fallback for UNAVAILABLE is acceptable during the migration period (Phases
1–5). The **target behaviour** after Phase 5 (when all paths provide activity) must be
specified before Phase 7.

**BLOCKED ON PRODUCT DECISION.** Must resolve before Phase 7.

---

## 17. Buffering and Backpressure

### 17.1 Per-stage buffer ownership

| Stage | Buffer | Max | Overload |
|-------|--------|-----|---------|
| Source adapter (FIFO) | OS pipe | OS-defined | OS drops; adapter sees EAGAIN |
| Source adapter (SHM) | 8192 stereo frames ≈ 185 ms | Fixed | Oldest overwritten by squeezelite |
| Canonicaliser (resampler) | Filter state + decoded-frame accumulation | Bounded (few ms) | — |
| STFT analysis window | 2048 samples | Fixed | — |
| BandNormaliser | EMA state | 0 (stateful) | — |
| OnsetEvent queue | Ring (e.g. 32 events) | Bounded | Drop OLDEST |
| SyncEngine delay ring | Scene ring | Fixed | — |

All stages remain bounded. Unbounded buffering breaks real-time lighting.

### 17.2 SHM catch-up (corrected)

The `n_new > VIS_BUF_SIZE // 2` condition in `SqueezeliteShmSource.read_new()` is a
**conservative catch-up/cap threshold**. It does NOT prove that a producer overwrite or
full ring lap occurred.

- When triggered: `n_new` is capped to `VIS_BUF_SIZE // 2` (4096 stereo frames). Some
  samples are discarded. Whether a full lap was missed is unknown.
- Actual full-lap loss cannot be reconstructed from the modular cursor position alone.
- Therefore: if continuity cannot be trusted after catch-up, treat this as a
  **conservative epoch invalidation policy** — emit a `StreamInvalidated` to reset
  analysis state. Lost duration remains unknown.

Do not describe the threshold as "confirmed overwrite." Distinguish observed/capped
delta from proven lost duration.

### 17.3 Unknown producer-side loss

Adapters do not always know how much audio was lost. Rules:
- Explicitly discarded frames (SHM catch-up cap) → lost count is bounded (but may be
  less than actual if a full lap was missed).
- SHM cursor advancement by an unknown number of ring laps → lost duration unknown.
- `TEMPORARILY_NO_DATA` (FIFO empty) → no loss implied; simply no data yet.
- Unknown continuity loss → new epoch; lost duration remains unknown.

### 17.4 Latency budget (informational estimates, not guarantees)

```
squeezelite SHM write          ~0 ms (at decode time)
read_new() SHM read            reads ≤ 185 ms window
Resampler 44.1→48 kHz          ~1–3 ms group delay (library-dependent; Phase 2)
STFT window (2048 @ 48000 Hz)  ~42.7 ms
STFT hop                       ~10 ms between frames
SyncEngine 30 Hz poll          0–33 ms jitter
HueDriver over DTLS            ~10 ms
Hue light response             ~50 ms
Total analysis-to-Hue          ~100–150 ms

Sonos playback buffer          ~2000 ms
Net light-leads-audio          ~1850 ms (compensated by latency ring buffer)
```

Resampler latency exact figure depends on library and parameters chosen in Phase 2.

---

## 18. Consumer Mapping

| Consumer | Current field | v1 field | Migration note |
|----------|-------------|---------|---------------|
| `spectrum_rgb` / `spectrum_rgb_spatial` bars | `bars` | `bars` | No change |
| `mono_pulse` brightness | `full` | `full` | Retained |
| `flashes` onset trigger | `onset` | `onset` (or OnsetEvent queue) | Phase 4 |
| `flashes` HPSS intensity | `hpss_active`, `percussive_energy` | `hpss_status == VALID`, `percussive_energy` | Phase 4 |
| `pulses` HPSS scale | `hpss_active`, `percussive_energy` | `hpss_status == VALID`, `percussive_energy` | Phase 4 |
| `fireworks` percussive scale | `hpss_active`, `percussive_energy` | same via status | Phase 4 |
| `swirl` brightness | `hpss_active`, `harmonic_energy`, `full` | same via status | Phase 4 |
| `wave` hue drift | `centroid` | `centroid` | No change |
| `wave` brightness | `hpss_active`, `harmonic_energy`, `full` | same via status | Phase 4 |
| `solid` hue drift | `centroid` | `centroid` | No change |
| `solid` brightness | `hpss_active`, `harmonic_energy`, `full` | same via status | Phase 4 |
| `EnergyProfile` blend input | `sustained_energy → full` | `activity (VALID) → fallback` | §16 |
| WebSocket `/ws/preview` | `sustained_energy`, `relative_exertion` | `activity`, `full` | Phase 6 |

**Confirmed corrections from v1.1:**
- `flashes` does NOT consume `onset_strength`; it uses `percussive_energy` for HPSS intensity.
- `spectrum_rgb` does NOT consume `centroid`; `_WaveRenderer` and `_SolidRenderer` do.
- Six effects use `hpss_active` (not five); `_SolidRenderer` is the sixth.

---

## 19. Safe Vertical-Slice Migration Plan

**Constraint**: no phase may intentionally leave production broken.

### Phase 0 — Freeze (DONE)

CAVA characterisation frozen. No further CAVA work.

### Phase 1 — New types only (no production change)

May begin after v1.2 design is approved.

Add to `types.py` or a new `canonicalizer.py`:
- `SourceReadResult` union (`DataResult`, `TemporarilyNoData`, `StreamInvalidated`,
  `EndOfStream`)
- `CanonicalReadResult` union (`CanonicalData`, `TemporarilyNoData`, `StreamInvalidated`,
  `EndOfStream`)
- `DecodedSourceFrame`, `AnalysisPcmFrame`, `InvalidationCause`
- `FeatureStatus`, `OnsetEvent`, `SpectrumLayout`
- Stub `AudioCanonicalizer` class

No existing code paths change. No behaviour change. Additive only.

Deliverables:
- New types matching v1.2 spec with docstrings
- Passing type checks and ruff
- Tests: type construction and field invariants

### Phase 2 — Decoded stereo source + canonicaliser + resampler selection

- Define the lifecycle-capable decoded-source protocol (returns `SourceReadResult`)
- Implement `SqueezeliteShmStereoSource` alongside (not replacing) existing `SqueezeliteShmSource`
- Implement `AirPlayPipeStereoSource` alongside existing `AirPlayPipeSource`
- Implement `AudioCanonicalizer` (accepts `SourceReadResult`, emits `CanonicalReadResult`)
- **Select resampler library here** (soxr or scipy); document flush semantics and
  group-delay offset; invariance tests must not compensate the same delay twice
- Verify: stereo round-trip, L≠R signal not collapsed to zero
- Verify: opposite-phase mono-equivalent cancellation does NOT occur in canonical output
- Do NOT yet attach to production analysis path
- **AirPlay rule**: a FIFO is a byte stream, not broadcast. Do not attach two independent
  readers to the production AirPlay FIFO simultaneously. Fan-out from a single ingress
  if both legacy and new consumers need data during transition.

Deliverables:
- `SourceReadResult` typed source protocol in new adapter classes
- `AudioCanonicalizer` with selected resampler
- Sample-pos continuity test; epoch-transition test (zero-output case handled)
- Production: old mono adapters and PcmAudioPipeline unchanged

### Phase 3 — Native AirPlay vertical slice

One complete path: `AirPlayPipeStereoSource` → `AudioCanonicalizer` → stereo-capable
`PcmAudioPipelineV2` → existing AudioFeatures.

**One ingress**: single reader on the AirPlay FIFO; fan-out if legacy path also needs data.  
**Native sample-derived timing from the start**: `dt = hop / sample_rate`, not wall-clock.  
An existing AudioFeatures compatibility projection may be produced during this phase.

Deliverables:
- AirPlay path produces stereo-correct features
- Opposite-phase sine → non-zero bars (anti-cancellation proof)
- All existing effects work on AirPlay path
- Legacy LMS paths unchanged

### Phase 4 — AudioFeatures semantic migration

Atomic enough to keep production working.

- Add `epoch_id`, `support_start_sample`, `support_end_sample`, `level`, `high`,
  `activity_status`, `hpss_status`, `SpectrumLayout`
- Rename `sustained_energy → activity`; keep deprecated alias one cycle
- `hpss_active: bool → hpss_status: FeatureStatus`
- `percussive_energy`, `harmonic_energy` → `float | None`
- Band boundary fix: exclusive Hz-based bass/mid/high (behaviour change — audit consumers)
- Remove `relative_exertion` (after WebSocket update)
- Update all six HPSS-consuming effects: check `hpss_status == VALID` instead of `hpss_active`
- Update CAVA path: CAVA compatibility timing representation (§11.7)
- WebSocket: send `activity`, `full` instead of `sustained_energy`, `relative_exertion`
- OnsetEvent queue introduced; `onset` snapshot field retained as compatibility projection

**OQ-C gate**: Phase 4 must either resolve bars activation anchors before freezing them
as a stable semantic contract, OR explicitly mark bars/onset_strength calibration as
provisional implementation-profile semantics tied to §12. Do not silently freeze
unresolved BandNormaliser anchors.

### Phase 5 — LMS stereo native path

Wire `SqueezeliteShmStereoSource` → `AudioCanonicalizer` → stereo `PcmAudioPipelineV2`
into the LMS-PCM-pipeline path.

Attach `SustainedEnergyTracker` and `PcmHpss` to `PcmAudioPipelineV2` (available when
configured/wired — **not** permanently mandatory).

`activity_status` will be VALID when wired, UNAVAILABLE when not. Do not state that
activity is permanently non-None after this phase.

Source-invariance test in this phase validates:
- Same candidate activity implementation + equivalent audio + equivalent SpectrumLayout
  → equivalent activity within test tolerance (±0.10)
- This does NOT validate OQ-A product semantics.

Legacy mono adapters and old CavaPipeline-based LMS path remain during this phase.

### Phase 6 — Consumer/legacy cleanup

- Remove deprecated `sustained_energy` alias
- Remove `beat`/`tempo` stubs (or gate behind explicit feature flags)
- Remove old mono interfaces (`PcmSource`, `SqueezeliteShmSource`, `AirPlayPipeSource`)
  only after grep/audit confirms no production consumer remains
- Do not remove a compatibility bridge still required by LayerMixer before Phase 7

### Phase 7 — EnergyProfile migration

**BLOCKED on OQ-B.** Also: if EnergyProfile intended low/high blend depends on OQ-A
activity semantics, OQ-A must also be resolved first.

Update `LayerMixer` to use explicit `activity_status` / `activity` with the policy from
§16. Remove `full` fallback for UNAVAILABLE (or retain as explicitly temporary).

### Phase 8 — Timing verification and CAVA cleanup

Native sample-derived timing was introduced in Phase 3. Phase 8 is:
- Verification of remaining dt usage
- Cleanup: convert `CavaPipeline`'s wall-clock dt to approximate audio cadence (~60 Hz)
  or document it explicitly as approximate
- CAVA compatibility timing representation cleanup

**Do not invent native support_start/end_sample for CAVA.**

### Phase 9 — CAVA retention decision

Decision: **deprecated and removed** for LampaStream's internal external-CAVA/FIFO
analysis route. Canonical PCM provides onset and HPSS parity (validated in
`d1f5e6d`); the hardware CPU comparison was settled by the user before this work.
See the “remove legacy bars_source=cava” task and [migration details](configuration.md).
Embedded cavacore remains supported. Squeezelite's named SHM ABI and independent
external stock consumers are unchanged.

---

## 20. Source Invariance Test Protocol

### 20.1 Source consistency vs semantic validation

**Source consistency**: same candidate implementation + equivalent audio + equivalent
SpectrumLayout → equivalent features within tolerance. Testable in Phase 5.

**Semantic validation**: validates whether the activity algorithm's product behaviour
(OQ-A) is correct. Requires product decisions. Phase 5 validation does not prove OQ-A.

### 20.2 Test protocol components

Each invariance test must specify:

1. **Signal alignment method**: e.g. cross-correlation, fixed resampler-delay trim
2. **Alignment bound**: maximum allowed shift; alignment must not "fit away" behaviour
3. **Start/end trimming**: discard first N hops (epoch/warmup artefacts)
4. **Gain preservation check**: verify `level` differences are within expectation;
   do not normalise for gain before comparison
5. **Onset matching rule**: ±1 hop (≈±10 ms) tolerance (consistent — one value)
6. **False positive/negative accounting**: separate FP and FN rates for onset tests

### 20.3 Invariance levels

**Level 1 — PCM-exact**: same S16_LE bytes → `max(|a − b|) < 1/32768`.

**Level 2 — Resampled equivalence**: same content at different rates.  
Signal alignment: resampler group-delay compensation (documented once in Phase 2;
invariance tests must not compensate the same delay twice).  
Tolerance: `max(|activity_a − activity_b|) < 0.05` at steady state.

**Level 3 — Lossy perceptual equivalence**: same music, lossless vs lossy codec.  
Tolerance: onset ±1 hop; activity ±0.15. Not bit-identical.  
"Same track from two services" must not be assumed to be the same audio master.

**Level 4 — Live stream equivalence**: AirPlay vs LMS. Additional jitter/latency allowance.

---

## 21. Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Stereo phase cancellation | **Critical** | Phase 3 power-mean channel policy |
| Six HPSS consumers need Phase 4 update simultaneously | **High** | Atomic transition; test all six in Phase 4 |
| Band boundary change breaks mid consumers | **High** | Audit all bass/mid consumers before Phase 4 |
| onset_strength not yet normalised | Medium | Phase 4: either normalise or mark provisional |
| Missing audio confused with musical silence | **High** | Typed `SourceReadResult`; lifecycle events |
| Epoch transition without any PCM frame | Medium | `StreamInvalidated` exists without DATA |
| Two readers on AirPlay FIFO | **Critical** | Phase 2/3 rule: one ingress, explicit fan-out |
| Resampler per-chunk rounding → sample_pos drift | Medium | Phase 2: accumulated rounding correction |
| EMA dt wall-clock (CAVA) | Medium | Phase 8; CAVA approximate cadence |
| State contamination across epochs | **High** | One reset per epoch boundary; §9.4 ordering |
| SHM ring overrun assumed as proved overwrite | Medium | Conservative epoch invalidation only |
| OQ-A/B unresolved at Phase 7 | **High** | Must resolve before Phase 7 begins |
| OQ-C unresolved at Phase 4 (bars semantics) | Medium | Phase 4 must mark bars as provisional if unresolved |
| HPSS CPU on all paths | Low | Profile on LXC before Phase 5 |
| Latency growth from resampler | Low | Bounded ~1–3 ms (Phase 2 selection) |
| AudioFeatures mutable in CAVA path | Medium | Phase 4: produce immutable snapshot |
| CAVA timing faked as native | **High** | §11.7: CAVA uses `approximate_wall_ns`; no fake support positions |

---

## 22. Non-Goals

- Removing CAVA immediately
- Making native DSP numerically equal to CAVA
- Beat tracking / BPM detection (deferred)
- Phrase / build / drop / structure detection
- ML-based music understanding
- New controller implementations (WLED, Nanoleaf, etc.)
- Zone refactoring; mobile or UI work
- Spotify/TIDAL/Roon integration (architecture accommodates; no adapter work)
- ReplayGain, loudness normalisation, per-track pre-analysis
- Reconfiguring shairport-sync to 48 kHz (adapter handles resampling)
- Spatial/stereo-width effects (deferred)
- Onset confidence scoring (distinct from strength; not in v1)

---

## 23. Resolved Questions

**RQ-1 — source_sample_pos for SHM**: use None; SHM buf_index is modular. Analysis
epoch-local sample_pos suffices for DSP timing.

**RQ-2 — Resampler library**: moved to **Phase 2** implementation decision. soxr
recommended; scipy.signal.resample_poly is the fallback. Phase 2 must document
flush semantics and group-delay compensation.

**RQ-3 — STFT window at 48 kHz**: retain 2048 samples (42.7 ms window, 10 ms hop).

**RQ-4 — Activity dB range (±6 dB)**: deferred to Phase 5 real-music validation.

**RQ-5 — HPSS CPU budget**: profile on LXC before Phase 5.

**RQ-6 — `high` boundary**: exclusive band from mid_hz to upper cutoff, following
`SpectrumLayout.mid_boundary_hz`.

**RQ-7 — CAVA timing**: CAVA uses `approximate_wall_ns`. No synthetic support positions.

**RQ-8 — level clamping**: clamp to [0.0, 1.0]; over-range reported via `over_range` flag.

**RQ-9 — Native BandNormaliser dt**: already uses `hop/sample_rate` in production
(`PcmAudioPipeline`). No migration needed for native path. CAVA path is outstanding
debt → Phase 8.

**RQ-10 — HPSS frequency filter**: full window width = 31 bins; half-width = 15 bins.
HPSS operates on magnitude frames; masks computed from squared magnitudes.

**RQ-11 — Onset flux domain**: magnitude differences (not power). Do not call native
onset "power-domain."

**RQ-12 — Effect consumer count**: six effects use `hpss_active` (Pulses, Flashes,
Fireworks, Swirl, Wave, Solid). Flashes does not use onset_strength. SpectrumRgb does
not use centroid. Wave and Solid use centroid.

---

## 24. Remaining Product Decisions

Must not be resolved in this document. Phase gates shown.

### OQ-A — Activity steady-state semantics

**Should sustained low-intensity music remain semantically LOW activity, or adapt toward
context-neutral (~0.5)?**

Under the candidate algorithm (for ordinary quiet above the 1e-4 gate): both EMAs
converge → activity tends toward ~0.5 over time. The product question is whether this
context-relative neutralisation is the intended behaviour for EnergyProfile blending.

**Does NOT block Phases 1–5.**  
**Must resolve before Phase 7.** May be validated empirically during Phase 5.

### OQ-B — EnergyProfile behaviour for non-VALID activity

**What is the target EnergyProfile output blend when activity is UNAVAILABLE or INVALID?**

`full` as a degraded fallback is acceptable during Phases 1–5. The target policy for
post-Phase-5 must be specified before Phase 7.

**Does NOT block Phases 1–5.**  
**Must resolve before Phase 7.**

### OQ-C — Spectrum activation anchors

**What do bars[i] = 0.0, bars[i] = 0.5, bars[i] = 1.0 mean for an Effect?**

The current BandNormaliser calibration (exertion_clip=3.0, attack/release τ) implicitly
defines these anchors, but they have not been validated against real music or committed
as a semantic contract.

**Does NOT block Phases 1–3.**  
**Must resolve before Phase 4 freezes bars as a stable semantic contract**, OR Phase 4
must explicitly mark bars/onset_strength calibration as provisional implementation-profile
semantics pending validation.
