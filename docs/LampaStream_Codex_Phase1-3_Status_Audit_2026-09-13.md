# HueSync — Independent Phase 1–3 Status Audit

**Source:** Codex read-only audit of `master@5ec6f5c`  
**Status:** `NEEDS CORRECTION`  
**Date:** 2026-09-13

> Tabellen/kolommen hieronder zijn in vaste-breedte tekstblokken gezet zodat de originele Codex-uitlijning behouden blijft.

---

• ## A. Executive verdict

  NEEDS CORRECTION

  The PCM-first foundation is real and worth retaining. AirPlay now reaches a phase-safe native analyser and drives
  lights, but the latest spectrum conditioning remains an experimental visualization model, and several lifecycle
  defects prevent calling the implementation production-ready.

  I verified that HEAD, master, and origin/master all resolve to 5ec6f5c. Production source and tests match that commit.
  The two modified installer scripts are excluded; untracked architecture documents and experiment artifacts are not
  treated as committed implementation or acceptance evidence.

  This was a read-only code/test audit. I did not run tests that create files or independently repeat the reported live
  experiments.

  ## B. What is proven working

  The committed code supports the live progress you reported:

  - One production AirPlay ingress: AirPlayPipeStereoSource replaces the old mono reader for AirPlay.
  - Explicit decoding: interleaved stereo S16 PCM becomes separate float32 L/R channels.
  - Canonicalization: stateful soxr resampling produces 48 kHz stereo PCM without AGC or loudness normalization.
  - Stable PCM storage: both published frame constructors copy their input and mark their owned arrays read-only.
  - Phase-safe analysis: independent channel FFTs are combined as
    sqrt((|L|² + |R|²) / 2).

  - Nonzero bars: the obsolete dB-byte route is absent from the active V2 calculation.
  - Audio-time DSP cadence: the current reference and decay calculations advance once per FFT hop, using 480 / 48000 =
    0.010 s.

  - Shairport idempotence: identical generated configuration returns without writing or restarting.
  - Compatibility wiring: V2 publishes existing AudioFeatures; Effects and LayerMixer can consume them.

  Your live evidence additionally establishes working reception, PCM delivery, nonzero FFT output, lights responding,
  and elimination of the unconditional restart storm. It does not establish final visual quality.

  ## C. What is not proven

  - That 5ec6f5c produces consistently useful colour balance across representative music.
  - That its spectrum preserves the particular dynamics HueSync wants to expose.
  - That onset events reliably survive the analyser-to-renderer handoff.
  - That reconnect, invalidation, idle EOF, and worker failures behave safely over long sessions.
  - That equivalent content through LMS and AirPlay produces equivalent features. LMS still uses the legacy analysis
    paths.

  - That all Effects remain perceptually compatible with the changed bar scale.
  - That EnergyProfile’s fallback remains musically useful after replacing per-band exertion with peak-normalized,
    decaying bars.

  - End-to-end latency, backlog behavior, and alignment with audible playback.
  - Complete resampler output accounting through clean EOS across different chunkings and rates.

  There is no evidence here requiring abandonment of native PCM analysis.

  ## D. Architecture compliance

  The main separation is correct. Transport decoding remains in adapters; representation conversion remains in the
  canonicalizer; musical conditioning occurs downstream.

  Important qualifications:

```text
   Area                   Assessment
  ━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Canonical format       Correct: 48 kHz, float32, stereo L/R. Mono duplication is supported.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Ownership              Correctness-first copies prevent producer reuse from changing published PCM. NumPy write
                          protection remains a cooperative contract, not protection against deliberately re-enabling
                          writes.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Source independence    V2’s calculations do not branch on AirPlay identity. However, production LMS does not yet use
                          V2.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Timing                 Hop-derived dt is correct for contiguous canonical PCM. V2 does not inspect sample_pos,
                          detect gaps, or publish sample support.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   AirPlay assumptions    Fixed 44.1 kHz/S16/stereo agrees with HueSync’s generated Shairport configuration. That is an
                          adapter contract, not inappropriate analyser leakage.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Feature boundary       Still deliberately legacy: no canonical timing/status metadata, no new dynamics fields, no
                          authoritative event delivery.
```

  Concrete violations and incomplete lifecycle handling:

  1. Invalidation leaves stale features published.
     _run() calls _reset_dsp() on StreamInvalidated, but neither clears _latest. A new epoch containing insufficient
     samples for an FFT also leaves the old snapshot visible. Reset happens again when the next epoch arrives,
     contradicting the exactly-once description. See V2 lifecycle handling (src/huesync/sync_engine.py:1049).

  2. FIFO EOF has two defects.
     AirPlayPipeStereoSource.read() returns EOS without clearing _remainder. A truncated old stream can therefore prefix
     bytes onto the next writer’s stream and corrupt channel/sample alignment. Repeated EOF also has no polling wait in
     V2, permitting a busy loop repeatedly rebuilding DSP state while no writer is present. See AirPlay source (src/
     huesync/pcm_source.py:662).

  3. SHM discarded audio is reported as temporary absence.
     The stereo reader advances _prev_index before copying. If its consistency check fails, it discards that interval
     but returns TemporarilyNoData; the next read does not retry the discarded interval. This silently joins separated
     audio within one epoch. Modular full-lap loss and source restarts are also not robustly detected. This adapter is
     not yet the production LMS path. See SHM reader (src/huesync/pcm_source.py:515).

  4. Canonicalizer continuity checks cover rate changes, not all identity/layout changes.
     Same-rate source_id replacement or mono/stereo changes do not automatically establish a new epoch. Current adapters
     are normally fixed-format instances, reducing immediate exposure, but the generic boundary is incomplete.

  5. Non-finite EOS output becomes valid zeros.
     Normal resampler output containing NaN/Inf causes invalidation; drain output containing them is replaced with zeros
     and published as CanonicalData. That contradicts the stated invalid-data semantics. Input frame constructors also
     do not reject non-finite samples before they enter soxr.

  6. Worker failure is not communicated through the lifecycle.
     An exception from the source, resampler, or analyser exits the daemon thread without clearing the last published
     features or exposing a structured failure.

  Also, clearing features does not itself guarantee lights fade: SyncEngine skips sending for None, leaving output-state
  behavior distinct from DSP-state behavior.

  ## E. Current native DSP path

  The active path is in PcmAudioPipelineV2 (src/huesync/sync_engine.py:767).

```text
   Stage                 Representation and conditioning                  Assessment
  ━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Analysis PCM          Float32 L/R, 48 kHz; nominal ±1, over-range      Correct source-independent foundation; no
                         retained                                         musical normalization.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   STFT                  Separate 2048-sample Hamming windows; 480-       Approximately 42.7 ms windows and 23.44 Hz
                         sample hop; unnormalized FFT magnitudes          bin spacing. Reasonable starting point, with
                                                                          limited low-frequency resolution.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Stereo combination    RMS-like magnitude across corresponding L/R      Phase-safe. Preserves channel energy in this
                         bins                                             representation; intentionally discards
                                                                          spatial information.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Log bands             Configured lower/upper cutoffs; exponential      Low bands can share bins because nominal
                         edges; rounded FFT-bin boundaries; exclusive     bandwidth is narrower than FFT resolution.
                         slices                                           These are not 30 independent frequency
                                                                          measurements.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Band aggregation      max(magnitude_bins)                              Measures the strongest component in each
                                                                          band, not integrated energy or mean spectral
                                                                          density. Removes mean-width dilution for
                                                                          isolated tones.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Squelch               Values <= 1e-3 FFT-magnitude units become        Fixed numerical floor, tied to this FFT/
                         zero                                             window scale. The claim that everything below
                                                                          it is quantization noise is too strong.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Adaptive reference    Maximum band magnitude feeds an EMA: 5 ms        One common reference avoids independently
                         attack, 1.5 s release                            flattening every band. It still removes
                                                                          sustained absolute-level information.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Normalization         min(band_magnitude / reference, 1)               Preserves simultaneous ratios only before
                                                                          clipping and subsequent independent decay.
                                                                          Dominant sustained components approach full
                                                                          scale.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Per-bar decay         max(previous × exp(-0.01/0.3), current)          Instant rise, exponential peak decay.
                                                                          Improves persistence but deliberately mixes
                                                                          spectral activity from different times.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Summary fields        bass: first 20%; mid: first 55%, cumulative;     Legacy compatibility, not a completed low/
                         full: all bars                                   mid/high semantic contract. No continuous
                                                                          high/treble field is emitted.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Centroid              Activation-weighted bar index divided by bar     Conditioned log-bar location, not physical
                         count                                            spectral centroid.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   Onsets                Separate detectors consume combined              Useful separation, but raw strengths and
                         magnitudes before bar normalization              latest-only delivery remain legacy behavior.
  ────────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────
   EnergyProfile         sustained_energy=None, so LayerMixer uses        Executable compatibility, not validated
                         full                                             musical activity.
```

  Every numerical stage is source-independent given identical canonical samples, configuration, history, and epoch
  handling. That does not establish production source invariance.

  Does it preserve musical dynamics? Partly:

  - Fast changes and relative spectral dominance remain visible.
  - Sustained gain differences are adapted away.
  - Strong attacks clip dominant bars.
  - Per-bar persistence can keep bass, mid, and treble simultaneously illuminated even when their attacks occurred
    separately.

  - A common reference can suppress other bands after a dominant bass transient.

  Those are visualization choices, not necessarily defects—but they must not be described as preserving dynamics without
  qualification.

  Is np.max appropriate?

  It is defensible for strongest-component activation, but not universally correct:

```text
   Aggregation                  Natural interpretation                   Main tradeoff
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Maximum                      Strongest resolved spectral component    Sensitive to peaks, bin placement, and
                                                                         extreme-value bias in wider noisy bands.
  ───────────────────────────  ───────────────────────────────────────  ────────────────────────────────────────────────
   RMS across bins              Typical spectral magnitude               Still dilutes sparse tones as band width
                                                                         grows.
  ───────────────────────────  ───────────────────────────────────────  ────────────────────────────────────────────────
   Sum of squared magnitudes    Band energy                              Wider bands naturally collect more broadband
                                                                         energy.
  ───────────────────────────  ───────────────────────────────────────  ────────────────────────────────────────────────
   Percentile                   Typical stronger components              Can discard isolated tones; depends strongly
                                                                         on bin count and percentile.
```

  A windowed musical note does not occupy exactly one bin, as the comment claims. Leakage, harmonics, overlapping
  instruments, and broadband percussion matter. The correct aggregation follows the intended bar meaning; one equal-tone
  test cannot select it.

  There is currently no explicit frequency-response compensation. That is not automatically a missing required filter:
  the unresolved issue is the desired tonal-versus-broadband response, not the absence of another DSP layer.

  Prior-art comparison

```text
   System                 Relevant lesson
  ━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   CAVA                   Treats bars as conditioned visual output, with sensitivity and display scaling. It is a
                          useful reference, not an amplitude or musical-activity truth source. Official configuration.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   WLED Audio Reactive    Uses grouped FFT data plus gain, frequency adjustment, smoothing, and scaling. Current source
                          uses fftAddAvg groups; it does not substantiate HueSync’s comment that np.max matches WLED.
                          Its smoothing is also not HueSync’s exact recurrence. Official source.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Lightjams              Exposes spectrum separately from higher-order musical information such as energy and beat-
                          related values. This supports distinct feature families. Official description.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   Light DJ               Describes intensity-dependent active/flowing behavior, colour changes, and beat-synced
                          effects separately. This is a product-semantic reference; its public page does not reveal the
                          underlying DSP. Official product page.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   QLC+                   Maps frequency-spectrum triggers to functions/channels and exposes volume separately. Audio
                          Triggers documentation.
  ─────────────────────  ───────────────────────────────────────────────────────────────────────────────────────────────
   xLights                Provides audio-level and other music-responsive effect modes with explicit thresholds and
                          display choices. It is not direct validation of a live native analyser. VU Meter
                          documentation.
```

  HueSync is aligned with established practice in using spectral analysis and temporal conditioning. The danger is
  repeatedly selecting conditioning by analogy while continuing to derive spectrum colour, transient response, and
  EnergyProfile activity from overlapping legacy quantities.

  Phase 4 foundation: the canonical PCM and preconditioned magnitude access make later separation easier. Freezing the
  current bars or full as general musical semantics would make it harder. Level/activity and future rhythm should not be
  reconstructed from these already-normalized, decaying bars.

  ## F. Superseded/dead experimental residue

  - V2’s signal-path docstring still says BandNormaliser performs its AGC.
  - Constructor comments still discuss _mag_to_bar_bytes, raw bytes, and the disabled gate.
  - V2 constructs and resets a BandNormaliser that its bar computation never calls.
  - normaliser, exertion_clip, and live update_exertion_clip() remain exposed, but changing that setting does not change
    V2 bars.

  - Tests explicitly preserve the unused normalizer and assert its gate, rather than testing active behavior.
  - Several test descriptions still mention per-band means, the old gate fix, or BandNormaliser timing.
  - The “matches WLED” justification for maximum aggregation and exact decay behavior is unsupported.
  - [pcm-v2 diag] runs at INFO every 50 FFT frames—approximately twice per second indefinitely. It is rate-limited, not
    limited to a finite diagnostic session.

  - The onset-method branch calls the same push_mag() operation on both sides.
  - The canonicalizer module still claims no production code imports it.
  - SpectrumLayout, FeatureStatus, and OnsetEvent exist but are not integrated into V2’s published feature path. These
    are intentional scaffolding, not necessarily removable dead code.

  - Legacy LMS/CAVA implementations are still needed; they are not abandoned experiment residue.

  No active dB-byte encoding remains in V2. There is also no hidden second BandNormaliser pass. The active conditioning
  consists of global reference adaptation followed by per-bar decay.

  ## G. Test-quality assessment

```text
   Category                              Evidence                                 Limitation
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Contract tests                        Shape, dtype, frozen metadata, owned-    Good basic coverage; finite input and
                                         buffer isolation, lifecycle variants,    some runtime type assumptions remain
                                         layout arithmetic                        unchecked.
  ────────────────────────────────────  ───────────────────────────────────────  ───────────────────────────────────────
   Canonicalizer implementation tests    Stereo/mono, rate changes, positions,    Not a complete rate/layout/restart/
                                         pending output, drain, gain              EOS accounting matrix.
                                         preservation
  ────────────────────────────────────  ───────────────────────────────────────  ───────────────────────────────────────
   Synthetic DSP tests                   Opposite phase, single-channel input,    Strong phase-safety evidence; weak
                                         tones, silence, broadband noise          musical-quality evidence.
  ────────────────────────────────────  ───────────────────────────────────────  ───────────────────────────────────────
   Component integration                 Real anonymous pipe → actual decoder     Bypasses the production worker,
                                         → soxr → actual V2 frame processing      named-FIFO reconnect behavior,
                                                                                  Shairport, renderer scheduling, and
                                                                                  Hue output.
  ────────────────────────────────────  ───────────────────────────────────────  ───────────────────────────────────────
   Compatibility tests                   Existing feature fields and renderer/    Mostly smoke tests; some construct
                                         LayerMixer calls                         features manually rather than
                                                                                  consuming V2 output.
  ────────────────────────────────────  ───────────────────────────────────────  ───────────────────────────────────────
   Production behavior                   Static activation checks plus user-      No comprehensive threaded lifecycle/
                                         reported live results                    visual acceptance regression.
```

  Specific false-confidence risks:

  - Lifecycle tests monkey-patch a duplicate dispatcher onto the class. They do not exercise _run(). They miss repeated-
    EOF spinning and verify neither snapshot invalidation nor exactly-once reset across the complete transition.

  - Chunk-independence testing is weak. A test described as “within 10%” accepts a ratio between 0.5 and 2.0, compares
    only the maximum, and can skip its meaningful assertions.

  - The equal-tone test is one-sided: low/high < 5 permits almost 5× low-frequency dominance and arbitrarily large high-
    frequency dominance.

  - “No mush” is tested with a pure 440 Hz sine. Sparse-tone contrast does not test dense mixes or temporal overlap.
  - Early 0.5-amplitude tones and σ=0.1 noise are valid numerical inputs but poorly represent the reported approximately
    0.003 live amplitude. Later low-amplitude tests are a valuable improvement.

  - Squelch tests often construct inputs directly from the implementation’s threshold. They prove the comparison works,
    not that the threshold represents musical/noise boundaries.

  - Canonical chunk tests use very low-frequency synthetic signals and do not drain the full stream in their chunk-
    equivalence helper.

  - The Shairport configuration test checks generated format fields; it does not verify repeated identical activation
    causes no restart.

  - A test requiring bars to remain above 50% after 100 ms proves persistence exists. It does not bound excessive
    persistence or colour overlap.

  ## H. Live-vs-tested matrix

  “Tested” below describes inspected coverage, not a fresh passing run. “Live proven” uses your supplied runtime
  evidence.

```text
   Area                           Unit tested    Integration tested    Live proven
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━
   PCM source                     YES            YES                   YES
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Canonicalization               YES            YES                   PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Resampling                     YES            YES                   PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Stereo phase safety            YES            YES                   NO
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Epoch/reset                    PARTIAL        PARTIAL               PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   FIFO lifecycle                 PARTIAL        PARTIAL               PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Shairport stability            PARTIAL        NO                    YES
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   FFT                            YES            YES                   YES
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Spectrum bars                  YES            YES                   YES
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Low/mid/high                   PARTIAL        PARTIAL               PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Visual quality                 NO             NO                    NO
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Source invariance              PARTIAL        NO                    NO
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   EnergyProfile compatibility    PARTIAL        PARTIAL               PARTIAL
  ─────────────────────────────  ─────────────  ────────────────────  ─────────────
   Effect compatibility           PARTIAL        PARTIAL               PARTIAL
```

  The earlier live opposite-phase characterization concerns the previous native path; it is not proof of the newly
  deployed V2 path, although V2’s synthetic phase tests are convincing.

  ## I. Technical debt by severity

  CRITICAL

  - None established at repository/system integrity level.

  HIGH

  - Stale snapshots survive invalidation, new-epoch warmup, and worker failure.
  - Repeated FIFO EOF can busy-loop; partial-byte carry can cross stream boundaries.
  - SHM torn-read discard silently violates continuity in the new adapter.
  - Latest-only feature publication can lose transient events between render polls or repeat a retained onset.
  - Current spectrum/colour and EnergyProfile fallback behavior lacks representative acceptance evidence.

  MEDIUM

  - Source/layout transitions and non-finite EOS handling are incomplete.
  - No feature sample-time provenance or sample-position continuity checks.
  - Legacy cumulative band fields disagree with Effects’ Hz-based exclusive grouping.
  - exertion_clip is a misleading no-op for V2.
  - Tests bypass production scheduling and contain permissive/vacuous assertions.
  - Source invariance remains unvalidated; the new LMS adapter is not production-wired.
  - No demonstrated bounded behavior under delayed processing, worker failure, or long idle sessions.

  LOW

  - Stale comments, unused normalizer construction, duplicate branch, temporary INFO diagnostics.
  - Architecture documents cited by code remain untracked rather than versioned with the implementation.

  ## J. Phase verdicts

```text
   Phase                       Verdict           Actually complete?
  ━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Phase 1                     GOOD              Core additive contracts are implemented and useful. Ownership and
                                                 tagged lifecycle results materially improve on the reviewed draft.
                                                 Some validation/documentation debt remains.
  ──────────────────────────  ────────────────  ────────────────────────────────────────────────────────────────────────
   Phase 2                     TECHNICAL DEBT    Core conversion works; not fully complete against lifecycle and
                                                 continuity guarantees.
  ──────────────────────────  ────────────────  ────────────────────────────────────────────────────────────────────────
   Phase 3 functional          TECHNICAL DEBT    Happy-path vertical slice is functionally delivered and live. Robust
                                                 lifecycle completion is not.
  ──────────────────────────  ────────────────  ────────────────────────────────────────────────────────────────────────
   Phase 3 production-ready    Not complete      Visual acceptance and concrete lifecycle defects remain outstanding.
```

  Native PCM is not yet ready to replace CAVA across production. This is a readiness judgment, not a rejection of the
  architecture.

  ## K. Single primary blocker

  There is no trustworthy, representative acceptance baseline for the current spectrum-to-light behavior.

  Successive fixes have established “nonzero,” “better isolated-tone contrast,” and “more persistence.” None establishes
  that the combined response produces the intended spectral colour separation and musical dynamics on real material.
  Without that baseline, another plausible aggregation or smoothing change risks repeating the same cycle.

  The lifecycle bugs are concrete corrections required alongside that validation; they do not require choosing a
  different DSP architecture.

  ## L. Maximum 3-step recovery plan

  1. Correct the demonstrated lifecycle defects without changing spectrum conditioning. Validate the actual worker path
     for invalidation, partial EOF/reconnect, idle EOF, and failure; cover SHM discarded-read continuity before using
     that adapter in production.

  2. Freeze the current DSP candidate and validate a small representative set. Include realistic-level music, sparse/
     dense passages, percussion, quiet transitions, and gain changes. Assess actual band-to-colour output and temporal
     overlap, not just nonzero/max metrics. Existing CAVA behavior may be a reference, never the acceptance oracle.

  3. Simplify and freeze only after acceptance. Retire unused V2 normalization machinery, misleading controls/comments,
     and temporary diagnostics; replace permissive regression assertions with the accepted behavior. Keep Phase 4 paused
     until that decision.

  ## M. Explicit recommendation

  Continue native PCM and temporarily retain CAVA alongside native. Preserve the canonical/stereo foundation, stop
  speculative DSP layering, and establish whether the current candidate is acceptable before changing it again. CAVA
  should remain an operational reference/compatibility option while native lifecycle correctness and visual quality are
  closed.

─ Worked for 3m 52s