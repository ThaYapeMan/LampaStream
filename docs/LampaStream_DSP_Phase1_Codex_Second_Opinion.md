# HueSync --- DSP Phase 1 Codex Second-Opinion Review

> Independent review of the HueSync audio architecture and Claude Code
> DSP Phase 1 audit. Source: Codex review, 2026-09-11. No production
> changes were made during the review.

The audit identifies the main architectural split, but several central
conclusions are incorrect or unproven. In particular, the claimed 3×
BandNormaliser time-constant difference is mathematically wrong,
native-path energy/HPSS provenance is misreported, and the proposed
comparison does not establish identical PCM consumption.

I reviewed the canonical document, current code at 72afbaf, and Claude's
September 11 DSP Phase 1 report recovered from its project conversation
archive. No files were changed or experiments run. The workspace
contains a CAVA 0.10.7+dfsg-1 package, but neither running CAVA nor
shairport-sync installations/configurations are accessible here.
Upstream-source findings below therefore do not certify deployed binary
behaviour.

A. Findings I confirm

The three implemented paths are:

Path Actual processing ━━━━━━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LMS → CAVA LMS → squeezelite's output/visualiser export → stereo SHM →
CAVA → raw 8-bit bar FIFO → FifoReader → CavaPipeline → BandNormaliser →
features ──────────────────
──────────────────────────────────────────────────────────────────────────────────────────────────
LMS → native Same squeezelite SHM → SqueezeliteShmSource → mono float32
→ PcmAudioPipeline → STFT → bar quantisation → BandNormaliser + PCM
onset → features ──────────────────
──────────────────────────────────────────────────────────────────────────────────────────────────
AirPlay → native AirPlay → shairport-sync pipe backend → FIFO →
AirPlayPipeSource → mono float32 → same native pipeline

The SHM export is a parallel output tap; it is not audio captured back
from snd-dummy. Upstream squeezelite exports its internal output samples
as 16-bit values and can apply ReplayGain during export. Squeezelite
exporter

bars_source is an LMS backend selector. AirPlay always uses the native
pipeline regardless of that field. The CAVA path also attempts to attach
an independent SHM tap for energy, optional HPSS and PCM onset.
Activation code (src/ huesync/player_manager.py:542)

The native spectral path uses:

-   (L+R)/(2×32768) mono conversion.
-   A 2048-sample Hamming window.
-   Hop size round(sample_rate × 0.010).
-   Mean magnitudes over approximately logarithmic frequency intervals.
-   Integer truncation and clipping to 8-bit before BandNormaliser.
-   BandNormaliser output quantised to bytes again.

At 44.1 kHz, the window spans about 46.4 ms and the hop is exactly 10
ms. STFT (src/huesync/pcm_source.py:226), native pipeline
(src/huesync/sync_engine.py:811)

CAVA's generated configuration leaves conditioning parameters
unspecified. Upstream 0.10.7 defaults include 60 FPS, autosensitivity
enabled, sensitivity 100%, and noise reduction 77%. Thus, raw output
means processed bars encoded in a raw format, not unconditioned FFT
magnitudes. Generated configuration
(src/huesync/player_manager.py:1100), CAVA defaults

B. Findings I dispute

1.  "BandNormaliser effective time constants differ by approximately
    3×."

The audit's per-call coefficients are approximately correct; its
per-second conclusion is false.

For constant input (x), while the same attack/release branch applies:

\[ E\_{n+1}-x=(E_n-x)e\^{-`\Delta `{=tex}t/`\tau`{=tex}} \]

After elapsed time (T):

\[ E(T)-x=(E(0)-x)e\^{-T/`\tau`{=tex}} \]

For the 700 ms release:

Update rate Release coefficient Residual after one second ━━━━━━━━━━━━━
━━━━━━━━━━━━━━━━━━━━━ ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 30 Hz 0.046503
0.239651 ───────────── ───────────────────── ───────────────────────────
100 Hz 0.014184 0.239651

The larger coefficient compensates for fewer calls.

There are differences in sampled transients, update phase, discarded
frames, and asymmetric branch selection. Also, output uses the previous
baseline, so its effective baseline age differs. These can affect
results without changing the configured exponential time constant.

The claim that attack tau becomes meaningless below 33 ms is too broad:
at 30 Hz, a 20 ms tau still gives alpha ≈0.811.

The first-call-dt finding is also incorrect: the EMA is seeded from the
first frame, making its first update delta zero. Startup alpha does not
distort that seeded state. BandNormaliser
(src/huesync/sync_engine.py:110)

2.  "CAVA gravity is a one-pole low-pass filter."

Upstream 0.10.7 implements falling-peak ballistics using a quadratic
fall counter, followed by an accumulating temporal recurrence.
Autosensitivity adjusts global gain. Its Hann windows are 8192 samples
for bass and 4096 for other bands at 44.1/48 kHz; it also applies
frequency-dependent weighting. These differ substantially from native
DSP.

The legacy gravity setting is parsed, but the core's falloff is driven
by noise_reduction and estimated frame rate. Treating every parsed
setting as active processing is unsafe. CAVA core

So additional conditioning is supported; the specific explanation and
claim that gravity is the dominant cause are not.

3.  "Downmix is identical across all three paths."

The two Python adapters downmix identically. CAVA 0.10.7 analyses stereo
channels separately and averages their resulting bars for mono output.
CAVA output handling

These operations are not equivalent:

\[ \|`\operatorname{FFT}`{=tex}((L+R)/2)\| `\ne`{=tex}
(\|`\operatorname{FFT}`{=tex}(L)\|+\|`\operatorname{FFT}`{=tex}(R)\|)/2
\]

For R = −L, native mono cancels completely; CAVA can retain substantial
energy. This is a major confounder for the proposed comparison.

4.  "Native paths provide sustained energy and optional HPSS."

They currently do not.

Only \_activate_lms_cava() calls engine.attach_shm_source(). Native LMS
and AirPlay give their source exclusively to PcmAudioPipeline, which
does not calculate sustained energy or HPSS. Consequently:

-   Native sustained_energy remains None.
-   Native HPSS fields remain at defaults.
-   LayerMixer falls back to relative exertion instead of the PCM energy
    tracker.

This is directly proven by the activation and processing code, and
materially undermines the audit's proposed energy comparison. Activation
(src/huesync/player_manager.py:594), feature enrichment
(src/huesync/sync_engine.py:1877), fallback
(src/huesync/sync_engine.py:1591)

Furthermore, existing HPSS produces harmonic/percussive summary
fractions. It does not route a harmonic spectrum into bars and a
percussive spectrum into onset detection as the audit states.

5.  "Missing resampling configuration proves unsafe AirPlay rate
    passthrough."

That inference is invalid: backend defaults can establish the output
format.

Current upstream AirPlay 2 pipe defaults are 48 kHz, S32_LE, stereo,
while its classic-AirPlay defaults are 44.1 kHz, S16_LE, stereo. Older
deployed revisions must be checked independently. Pipe implementation

HueSync's setup builds from an unpinned upstream checkout with AirPlay 2
enabled. Both configuration generators specify only the backend and pipe
name. Therefore:

-   The Python assumption is real.
-   Its mismatch with the deployed receiver remains unverified.
-   With current upstream defaults, the potential mismatch includes
    sample width, not merely rate.
-   The audit's proposed resample_rate_request fix is not substantiated;
    current pipe documentation uses output_rate, output_format, and
    output_channels. Configuration documentation

Do not apply that suggested fix blindly.

C. Findings that remain hypotheses

The following are plausible, but not established by this audit or the
repository:

-   CAVA conditioning is the principal reason lights appear more stable.
-   AirPlay PCM has a wrong rate, wrong sample width, or elevated noise
    floor in the deployed system.
-   SHM tearing or dropped exports occur often enough to affect visible
    behaviour.
-   Scheduling jitter has negligible impact on sustained energy.
-   Same-track playback through different applications/devices produces
    equivalent PCM.
-   Adding native smoothing would improve musical usefulness.

Decoded PCM does not guarantee identical mastering, codec artefacts,
volume, EQ, channel treatment, or sample timing. The audit itself
acknowledges application loudness processing, contradicting its broader
statement that sender application is no longer a variable.

D. Important blind spots

SHM is readable by multiple independent consumers, but it is not a
reliable broadcast stream.

SqueezeliteShmSource maps read-only and maintains a private
\_prev_index. Separate instances do not steal each other's samples.
Conversely, sharing one instance between consumers advances the same
cursor, splitting delivery; concurrent seek/read operations also lack
protection. SHM reader (src/huesync/pcm_source.py:87)

Its limitations include:

-   The ring holds 8192 stereo frames: about 186 ms at 44.1 kHz.

-   Modulo subtraction cannot detect full laps; exactly one lap can
    appear as zero new samples.

-   The half-ring policy discards history after approximately 93 ms of
    accumulation, even before a full overwrite.

-   The post-copy index check is not a true sequence lock. An unchanged
    index cannot prove the writer was inactive during the copy.

-   When that check rejects a block, \_prev_index has already advanced.
    Lost samples are not represented as a discontinuity.

-   Header size, ABI, endianness and ring capacity are assumed.

-   Writer restarts, stale mappings and midstream rate changes have no
    explicit recovery contract.

The upstream CAVA SHM implementation inspected also copies fixed ring
locations without reconstructing the chronological stream from
buf_index; its sleep calculation merits investigation. That means "same
SHM" cannot be assumed to mean "same ordered samples and windows." This
finding is from upstream master; the installed 0.10.7 reader still needs
verification. CAVA SHM reader

FIFO readers have different semantics. Two readers on AirPlay's FIFO
consume portions of one stream; they do not each receive a copy.
Claude's suggested extra pipe reader or wc -c can therefore interfere
with production analysis. The same applies to attaching another reader
to the production CAVA output FIFO.

Timing is mixed and sometimes loses events.

-   CAVA normalisation uses elapsed wall time whenever latest() is
    called, including repeated reads of an unchanged frame.

-   Native normalisation uses audio-hop time for every processed frame,
    but silently lost samples compress that timeline.

-   Rendering sleeps 1/30 second after work, so actual cadence is slower
    and variable.

-   Native features use a latest-value slot: onset events between render
    polls can disappear.

-   CAVA PCM multiband/superflux enrichment also selects the last result
    in a batch.

-   No sample timestamps link CAVA bars, PCM onset and rendering. The
    claimed ≤33 ms alignment bound is unsupported.

-   Native DSP reads sample rate when initialising, then does not
    rebuild when the SHM rate changes.

-   AirPlay partial stereo-frame bytes are discarded instead of retained
    for the next read.

Feature provenance is less consistent than reported. In the CAVA path,
PCM enrichment replaces aggregate onset, but not aggregate
onset_strength. Those fields can describe different analyses. bass, mid,
and full are cumulative averages of normalised exertion bars---not
physical band energies. centroid is weighted bar position, not a Hz
centroid.

PcmSource is useful, but incomplete. It already isolates transport and
standardises mono float32 amplitude. That is substantive reuse. However,
it lacks sample positions, timestamps, discontinuity/rate-change
signalling, ownership rules and buffering guarantees. Even lifecycle
signatures differ: the protocol declares open(), whereas SHM requires
open(mac). Protocol (src/huesync/pcm_source.py:36)

It is a useful adapter boundary, not yet the canonical audio contract
described in the target document.

E. Is the proposed same-PCM experiment valid?

As an exploratory same-source comparison: yes. As a controlled
identical-PCM experiment using the current script: no.

compare_bars.py already starts a separate CAVA process/FIFO and an
independent SHM reader, performs native STFT/bar computation, and
normalises every native frame. The report's claim that this must first
be added is incorrect. Comparison script (scripts/compare_bars.py:309)

However, it:

-   Reimplements the spectral subset rather than exercising the full
    production pipeline.
-   Samples latest values roughly once per second without sample
    alignment.
-   Computes standard deviation across bars, not temporal jitter per
    bar.
-   Reports cosine similarity, not Pearson correlation or measured lag.
-   Does not capture onset, sustained energy, HPSS or sample loss.
-   Uses default exertion_clip rather than loading that production
    setting.
-   Can continue reporting stale data or incorporate missing data as
    zero vectors.
-   Cannot neutralise the different stereo treatment or SHM read
    histories.

It can expose large differences. It cannot attribute them specifically
to smoothing, prove backend equivalence, or justify an energy refactor.

Running it would also create temporary files/FIFOs and start processes,
so I did not run it under this review's constraints.

F. Smallest next experiment I recommend

First establish the deployed CAVA and shairport-sync versions, build
revisions, effective configuration and backend format. This is a
prerequisite, particularly because of the possible S32_LE AirPlay
mismatch.

Then run a short diagnostic-only replay experiment using one known PCM
sequence: silence → steady tone → amplitude step → silence, with
identical left/right channels.

Feed independent copies of those exact samples to both analysers,
preserving native-rate outputs and recording sample positions or a
defined replay timeline. Compare:

-   Raw and conditioned per-bar step responses.
-   Attack/release duration.
-   Temporal variance during the steady tone.
-   Gate/clipping behaviour.
-   Missing/repeated input or output frames.

This requires diagnostic work, not production refactoring. Keep CAVA's
production conditioning initially. A subsequent opposite-phase stereo
segment would isolate the downmix difference. Separately, a
deterministic BandNormaliser test at 30/100 Hz can verify its
coefficients without any audio transport.

G. What should not be refactored yet

-   Do not unify normaliser call rates to fix the nonexistent 3×
    time-constant error.
-   Do not add smoothing or retune AGC based on the current comparison
    statistics.
-   Do not choose a canonical sample rate or replace CAVA yet.
-   Do not add an extra consumer of the existing AirPlay FIFO.
-   Do not attach the same PcmSource instance to two independently
    reading pipelines.
-   Do not tune Energy Engine v2 while native and CAVA paths use
    different energy inputs.
-   Do not rename bars_source or replace AudioFeatures merely to match
    the target diagram.

The immediate work is to establish deployed format behaviour, document
the missing native energy/HPSS provenance, and obtain measurements with
known input and timing.
