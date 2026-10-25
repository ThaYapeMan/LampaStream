# Code and contract map

Descriptive snapshot of baseline commit
**3998c440f464d0cf02743633fba98e8dd990743b**, recorded **2026-10-24**.
All `file:line` references below are relative to `src/lampastream/`, unless a
repository path or dependency is named. Line numbers refer to that full commit,
so later comment edits do not change the evidence anchor. This maps implemented
behavior, not measured musical quality or a proposal. See [baseline.md](baseline.md).

## Sources and canonical analysis

`pcm_source.py:49` defines the physical-source protocol; `pcm_source.py:364`
implements LMS stereo SHM and `pcm_source.py:1166` the 44.1 kHz S16_LE stereo
AirPlay pipe. `airplay_early.py:107` owns early-tap reading and regular-pipe
fallback. `lms_timing.py:300` wraps LMS PCM with measured play-time provenance.
Source events distinguish data, temporarily no data, invalidation and EOS
(`canonicalizer.py:92`). `PlayerManager` owns sessions and physical sources;
activation/deactivation and retirement gating live in `player_manager.py:631`
and `player_manager.py:1000`, while
`sync_engine.py:3076` retains analysers that cannot yet stop. The manager must
not close a source still used by any worker.

`AudioCanonicalizer` (`canonicalizer.py:351`) converts decoded mono/stereo to
**48,000 Hz, two-channel float32**, nominally [-1,1], duplicates mono, and uses
soxr for resampling. The immutable owned PCM frames carry epochs and canonical
sample positions (`canonicalizer.py:139`); these are not wall-clock times.
Clean EOS drains valid resampler carry; invalidation discards uncertain carry.

`CanonicalAnalysisPipeline` (`sync_engine.py:983`) owns canonicalization, shared
STFT, processors, epochs, EOS/reset, publication and the analysis worker.
`StereoMagStft` (`sync_engine.py:731`) combines independent channel magnitudes as
`sqrt((L²+R²)/2)` without phase-cancelling downmix. `SharedAnalysisFrame`
(`spectrum_engine.py:82`) contains PCM, magnitudes and chunk-independent hop
positions. The worker sequentially feeds Spectrum, Beat, Loudness and optional
HPSS (`sync_engine.py:1039`, `sync_engine.py:1385`).

`AudioFeatures` (`types.py:116`) holds bars, cumulative bass/mid/full aggregates,
centroid, onset flags/strengths, HPSS fractions, sustained energy, level, LUFS and
optional receipt/play provenance. `PublicationRecord` (`spectrum_engine.py:127`)
binds those values to sequence, epoch, exact `[sample_pos,sample_end)`, effective
engine, fresh processor IDs and optional carried Spectrum interval.

`sync_engine.py:1478` groups contributions by **exact interval**, emits Spectrum
keys first and then other first-seen keys, and never unions intervals or pairs by
list position. A late contribution creates a new record; it does not mutate an
older publication. History can supply Spectrum bars from an exact interval or a
completed interval ending no later than the contribution's start; provenance is
explicit. With no such history, bars are empty and the contribution survives.
`sync_engine.py:1248` commits sequence, queue and latest under one lock. Sequence
orders delivery; `latest()` selects freshest audio `(sample_end,sample_start)`
within the epoch, preferring later delivery on ties. Late records stay queued
without rewinding latest. History and publication queues are bounded at 1,000;
queue overflow is counted, not a guarantee of complete event delivery.

## Processors and conditioning

The defaults below are from `models.py:225`, `models.py:242` and the implementation
constants. A 480-sample hop at 48 kHz is **100 Hz in source audio**, not a measured
wall-clock deadline. Shared STFT windows contain 2,048 samples with a Hamming
window (`pcm_source.py:123`, `pcm_source.py:225`). Hop intervals describe reporting
positions; they do not claim that only those 480 samples were used in analysis.

| Processor / conditioning | Input → output | Rate, tunables and defaults |
|---|---|---|
| V2 Spectrum (`spectrum_engine.py:261`) | Shared stereo magnitudes → logarithmic max-bin bars, pink compensation, peak-normalized/clamped/falling bars; canonical assembly derives bass/mid/full/centroid | One update per shared 480-sample hop after window warmup. `bars=30`, cutoffs `50–12000 Hz`, `bar_falloff_s=0.3`; internal noise floor `1e-3`, peak EMA attack `0.005 s`, release `1.5 s` (`spectrum_engine.py:37`, `spectrum_engine.py:323`). |
| CavaCore Spectrum (`spectrum_engine.py:398`) | Canonical stereo PCM, float64 interleaved ×32768 → separately conditioned channel bars, averaged; own Hann FFTs (4096 normal / 8192 bass) | Executes 480-frame blocks, 100 Hz; short EOS block padded internally but published end clamped to valid PCM. Same bar/cutoff configuration; `autosens=1`, `noise_reduction=0.77`, linear scaling (`spectrum_engine.py:434`); native sensitivity/integral/gravity remain CAVA's conditioning. No V2 conditioning is reapplied. |
| Combined onset (`sync_engine.py:497`) | Shared magnitudes → positive spectral-flux sum → Dixon → `onset`, `onset_strength` | Shared 100 Hz hops; `onset_method=combined`, `onset_delta=0.1`, `onset_alpha=0.9`; no BPM or phase estimate. |
| Multiband onset (`sync_engine.py:649`) | Shared magnitudes split into independent bass/mid/treble flux/Dixon detectors → three flags and strengths; aggregate onset OR and maximum strength (`sync_engine.py:883`) | Shared 100 Hz hops; same delta/alpha; boundaries `bass_hz=250`, `mid_hz=2000`. |
| SuperFlux onset (`sync_engine.py:539`) | Half-wave difference from maximum-filtered lagged magnitude → Dixon → aggregate onset/strength | Shared 100 Hz hops; `superflux_mu=3` bin half-width, `superflux_lag=2` hops, same delta/alpha. |
| Dixon picker (`sync_engine.py:366`, `sync_engine.py:444`) | Normalized flux → local-maximum, asymmetric-mean-plus-delta and decaying-threshold tests | Internal `W=3`, `M=3`, 13-frame buffer, 30-frame warmup, normalization EMA alpha `0.1`. Candidate index 9 has three later frames of evidence. The returned strength is the **current** raw flux, not the candidate's historical strength; Beat publishes the current shared-hop interval (`sync_engine.py:911`). |
| Loudness (`loudness_analyzer.py:10`, `loudness_meter.py:39`) | Canonical stereo PCM → `loudness_momentary_lufs`, `loudness_short_term_lufs`, unweighted phase-safe RMS `level` | Reports each shared hop after window completion. Fixed 48 kHz BS.1770 K-weighting, stereo weights 1, offset −0.691, 400 ms / 3 s windows; no integrated-programme gating. `None` during warmup, `-inf` below −70 LUFS; JSON maps nonfinite values to null. No user DSP tunables. Raw RMS window is 2,048 samples. |
| HPSS (`hpss_analyzer.py:14`, `pcm_source.py:277`) | Canonical `(L+R)/2` PCM → independent rolling STFT/median masks → `percussive_energy`, `harmonic_energy`, assembly sets `hpss_active` | Optional `use_hpss_separation=false`; 2,048-sample Hamming window, 480-sample hop, harmonic history 17 frames, percussive median width 31 bins (`pcm_source.py:217`). Fractions approximate shares, not separated audio outputs. No padded EOS readings; downmix can cancel anti-phase stereo. |
| Band normaliser (`sync_engine.py:135`, `sync_engine.py:1188`) | Fresh Spectrum bars, quantized to bytes → per-band relative-to-EMA exertion bars | Canonical `band_normalise=false`; `exertion_clip=3.0`, internal attack `0.005 s`, release `0.700 s`, mean-byte silence gate `5`. Runs once per fresh Spectrum interval after either engine, not on carried historical bars; preview/Effects share normalized bars. Raw scalar aggregates stay unchanged. External FIFO uses the same normaliser at its caller cadence. |

`SpectrumProcessor` adapts engine blocks and exact intervals; `AnalysisProcessor`
is the common feed/flush/reset/close protocol (`spectrum_engine.py:144`). Loudness
is always in the canonical stack; HPSS is enabled by configuration. Chroma is
**not delivered**: `ChromaAnalyzer` (`spectrum_engine.py:199`) is a protocol only.

## Energy and layer blending

`SustainedEnergyTracker` (`sync_engine.py:277`) receives each canonical PCM block,
computes short/long RMS EMAs and their log ratio: defaults **0.300 s / 30 s**, range
**±6 dB**, silence threshold **1e-4**. Silence holds its value. It is separate from
bar normalization and raw momentary RMS.

`EnergyInput` (`energy_input.py:12`) selects a scalar before mixing. Persisted
parameters/defaults are in `models.py:211` and `models.py:213`:

| Source | Input and parameters |
|---|---|
| `sustained` (default) | `sustained_energy`, falling back to `full` when absent. |
| `loudness_fixed` | Momentary LUFS linearly mapped/clamped between `lufs_floor=-30` and `lufs_ceiling=-8`. Warmup/nonfinite → zero. |
| `loudness_adaptive` | Momentary LUFS; initial bounds −30/−8; expand with 1 s time constant, contract with `adaptation_tau_s=60`; minimum span 6 LU; silence does not train the window. |
| `peak_envelope` | `level` divided by its amplitude envelope, clamped [0,1]. `peak_envelope_auto=true` uses attack `0.05 s`, release `2 s`; manual values default to those same values. `peak_reshape_enabled=false`; when enabled, replaces level with mean of nonnegative `bars ** peak_reshape_power`, default power `0.4`. Invalid inputs → zero. |
| `off` | Constant 1, selecting the active layer through the existing mixer. |

`LayerMixer` (`sync_engine.py:2656`) renders both Effects, maps selected energy
through cubic smoothstep between `blend_start=0.3` and `blend_end=0.7`, then updates
`mix += blend_response * (target-mix)` with `blend_response=0.1`. That EMA is
**render-rate dependent**, unlike the elapsed-time energy envelopes. Low mix
selects the mellow layer; high mix the active layer; the middle returns a LerpScene.

`SmoothLayerMixer` (`sync_engine.py:2709`) renders old/new mixers through a shared
transition phase. `transitions.py:34` starts the phase when the output samples it,
not at PCM receipt; an interrupted transition can freeze the shown scene as its
baseline. Modes are crossfade, through-black and through-white
(`transitions.py:8`); defaults are crossfade and **0.7 s** (`models.py:202`).
Old and new renderers may both advance during a transition.

## Renderers

The factory has **14 effect types** (`models.py:67`, `sync_engine.py:2529`). Entries
below describe renderer-specific feature reads, before shared palette wrapping.
No renderer directly reads per-band onset flags/strengths, `level`, or LUFS;
those latter fields can drive EnergyInput. Generic onset is not a beat grid.
Defaults: sensitivity 1, brightness floor 0.15, speed 1, decay 0.3, onset flash
intensity 0 (`models.py:198`).

| Type / implementation | AudioFeatures consumed | brightness_floor | State / cadence |
|---|---|---|---|
| `spectrum_rgb` (`sync_engine.py:1973`) | bars, onset | No | Stateless RGB mapping/optional onset lift. |
| `spectrum_rgb_spatial` (`sync_engine.py:2028`) | bars, onset | No | Stateless spatial RGB mapping. |
| `band_colours` (`sync_engine.py:2067`) | bars, onset | No | Colour playback/order and last-advance state; onset advancement depends on calls observing onset; timer mode uses elapsed time. |
| `band_colours_spatial` (`sync_engine.py:2160`) | bars, onset | No | Same playback state as band_colours; spatial scene. |
| `mono_pulse` (`sync_engine.py:2168`) | bars, onset | Yes | Stateless white energy mapping. |
| `pulses` (`sync_engine.py:2183`) | bars, onset; conditional HPSS percussive fraction | Yes | Captured hue and envelope; attack gain 0.7 per onset call, decay ×`(1-min(decay,0.99))` on other calls: **render-rate dependent**. |
| `flashes` (`sync_engine.py:2233`) | onset; conditional HPSS percussive fraction | Yes, ×0.3 | Envelope decays every call ×`(1-min(2*decay,0.99))`; cooldown set to **4 ticks**, decremented each call: **render-rate dependent**. |
| `splotches` (`sync_engine.py:2273`) | onset | Yes | Seed and envelope; non-onset decay ×`(1-min(0.5*decay,0.99))`: **render-rate dependent**. |
| `fireworks` (`sync_engine.py:2367`) | bars, onset; conditional HPSS percussive fraction controls speed | No | Origin/particles/birth time retained; each observed onset replaces burst. Scene trails decay with elapsed age at `3*decay`, flash at `6*decay`; onset observation still depends on render calls. |
| `swirl` (`sync_engine.py:2435`) | full; conditional harmonic fraction | Yes | Time-based spatial motion. |
| `wave` (`sync_engine.py:2466`) | full, centroid; conditional harmonic fraction | Yes | Hue EMA gain 0.02 per call: **render-rate dependent**; wave motion uses time. |
| `solid` (`sync_engine.py:2482`) | full, centroid; conditional harmonic fraction | Yes | Hue EMA gain 0.01 per call: **render-rate dependent**. |
| `gradient` (`sync_engine.py:2498`) | full, centroid; conditional harmonic fraction | Yes | Stateless centroid-to-curated-palette mapping. |
| `none` (`sync_engine.py:2522`) | None | No | Always black. |

`ColourModeEffect` (`sync_engine.py:2604`) optionally wraps scenes in `PaletteScene`
(`sync_engine.py:2570`), using spectrum scene RGB weights, spatial coordinates, captured hue or
centroid for palette position, palette rotation and the original scene's
brightness. Thus palette wrapping can add centroid use to the base renderer table; it does not replace the renderer's envelope timing.

## Output routes and Hue transport

Normal route: `SEND_INTERVAL_S=1/30` (`sync_engine.py:76`), then each loop polls
`latest()` (`sync_engine.py:3210`), copies freshest loudness/level/HPSS for rendering,
and appends one Scene (or None) to a delay deque. Target depth is rounded from
milliseconds to ticks. `sync_engine.py:3273` pops **while** depth exceeds target;
a delay reduction can therefore send several scenes in one tick. Repeated polling
can reuse an onset, or miss onsets between snapshots. This is not queue delivery
of every analysis event, nor an exactly 30 Hz wire guarantee under load.

Timestamped route: AirPlay early tap or LMS head start activates
`sync_engine.py:3169`. It drains PublicationRecords, rejects missing play times or
stale timing generations, renders scenes and adds them to `SceneSchedule`
(`airplay_early.py:333`). Target is `max(ready, play+trim_ms/1000)`. Capacity is
1,000; overflow removes the earliest entry. Each output tick consumes due entries
but sends only the last due scene. Reset/flush generations clear old scenes.
LMS may use the SHM player clock or a write-clock estimate (`lms_timing.py:349`);
AirPlay maps paired raw/monotonic clocks (`airplay_early.py:49`). These clocks are
software playout estimates, not measured acoustic arrival at a listener.

`HueDriver.send` (`hue_output.py:399`) samples each scene at channel positions and
the send timestamp. `Colour.to_16bit` (`types.py:38`) supplies 0–65535 commands to
`hue-entertainment`; the driver sends only while streaming and requests recovery
on failure. In the locally installed **hue-entertainment 0.1.2**, dependency
`hue_entertainment/dtls.py:183` builds HueStream v2 RGB colour-space **0x00**:
16-byte header, 36-byte area UUID, 7 bytes/channel. Lines 205–208 reduce command
components to **8-bit effective values** (right shift for values >255) and duplicate
each byte into the two component bytes. Thus the local transport is not 16-bit
colour precision despite the driver command API. This dependency evidence is
outside the repository; `pyproject.toml` permits newer versions, so record the
installed version in subsequent measurements. Enqueue/send-call time is not a
DTLS transmit acknowledgement or a lamp-response timestamp.

## Metadata and musical context

`TrackPositionSource` is a separately owned metadata channel, outside PCM and
AudioFeatures (`track_position.py:1`; session wiring in `player_manager.py:324`).
`MusicDirector` (`music.py:26`) runs independently of rendering, checks current
track/configuration every 0.5 s, and rejects stale track responses before applying
choices (`music.py:94`).

Genre resolution (`genres.py:133`) first maps track tags, then optionally Last.fm
track tags and artist fallback. Requests are bounded/cached and off the audio
path. `matching_rule` (`genres.py:151`) returns **palette and EnergyProfile IDs
only**, each independently overridden by a nonempty manual coupling choice.
`MusicDirector.step` applies a replaced coupling with the selected EnergyProfile
and palette; it does **not** change the Analyser or onset algorithm. Existing
rules do not add a separate DSP direction layer.

Album art (`album_art.py:94`, `album_art.py:133`, `music.py:46`) is bounded,
quantized with Pillow, merged/selected in perceptual colour space and cached.
Failed/unusable artwork preserves the current palette; monochrome-cover fallback
can use the genre palette. Palette selection and transitions affect rendering,
not the PCM feature stream. See [music-colours.md](music-colours.md) for the
existing context and colour decisions.

## Contracts to preserve

1. **Source ownership:** PlayerManager owns physical sources/session resources;
   canonical workers own DSP. Stop timeout retains worker and source ownership;
   retry teardown before closing or starting another reader (`sync_engine.py:1743`,
   `sync_engine.py:3076`; [audio-pipeline.md](audio-pipeline.md)).
2. **PCM format:** source adapters decode/alignment-check frames; canonical output
   is owned/read-only 48 kHz stereo float32. Mono duplication and soxr conversion
   belong to canonicalization, not Effects (`canonicalizer.py:139`).
3. **Epochs:** uncertain continuity is invalidated before new PCM; epochs reset
   DSP, shared clocks/history and live snapshots. No silent insertion of guessed
   audio; temporary no-data is not EOS (`sync_engine.py:1230`, `sync_engine.py:1676`).
4. **Exact intervals:** processor updates retain their actual half-open sample
   intervals across arbitrary chunks and EOS; no positional pairing, union or
   padded source-duration claim (`sync_engine.py:1478`, `sync_engine.py:1602`).
5. **Publication semantics:** delivery sequence and audio time are different;
   valid late updates survive, latest cannot rewind, carried bars have explicit
   history provenance, and bounded-queue drops remain observable
   (`sync_engine.py:1248`, `sync_engine.py:1657`).
6. **Metadata outside DSP:** track position, tags, artwork and genre resolution
   remain a separate session channel; they do not enter PCM, processors or
   AudioFeatures ([audio-pipeline.md](audio-pipeline.md#independent-track-metadata-channel)).
7. **Producer ABI:** canonical LMS requires SHM **v1** from yeney-player, pinned
   to **45779a4383929840a46a931fc1519b4778b64a72** in installer and gitlink.
   Preserve the v1 prefix and coherent generation/gap/absolute-position contract;
   optional YNPT timing is a 64-byte tail, not a replacement PCM ABI
   (`pcm_source.py:143`, `player_clock.py:13`; [SHM ABI](../squeezelite/README.md)).

## EVENT-01 phase 2 additions

`types.py` defines immutable OnsetEvent candidate/confirmation/play coordinates and
OutputCapabilities. `OnsetDetector.process_event` and process_odf_event expose
candidate metadata; the boolean methods remain compatibility adapters. BeatDetector
emits candidate-hop ProcessorUpdates and combines band votes over 30 ms.
CanonicalAnalysisPipeline owns drain_events beside the continuous publication queue.
SyncEngine drains events on both routes and projects them onto each scene's clock.
`onset_envelope.py` contains TriggerEnvelope hold/release and retrigger policies.
`output_boundary.py` guards output precision at scene sampling, outside renderers.
`trace_output.py` loads capabilities from room JSON; replay_chain exports events.csv
and independent event-disposition counters. The baseline sections above retain their
original revision anchor; these additions replace its boolean onset path only.
