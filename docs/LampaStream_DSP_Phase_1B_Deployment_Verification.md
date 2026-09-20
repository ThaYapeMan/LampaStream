HueSync DSP Phase 1B --- Deployment Verification

  ---------------------------------------------------------------------------------------------------------------------------------
  1\. Executive Summary
  ---------------------------------------------------------------------------------------------------------------------------------
  2\. Deployment Inventory

  ┌────────────────┬───────────────────────────────────┬──────────┬───────────────────────────────────────────┬─────────────────┐ │
  Component │ Version/build │ Running? │ Config/source │ Confidence │
  ├────────────────┼───────────────────────────────────┼──────────┼───────────────────────────────────────────┼─────────────────┤ │
  HueSync │ 0.2.0 (pyproject.toml); commit │ UNKNOWN │ /opt/huesync (expected per CLAUDE.md) │ REPO FACT; │ │ │ 72afbaf │ │ │
  runtime UNKNOWN │
  ├────────────────┼───────────────────────────────────┼──────────┼───────────────────────────────────────────┼─────────────────┤ │
  squeezelite │ UNKNOWN │ UNKNOWN │ Launched by player_manager.py with -v │ UNKNOWN │ │ │ │ │ flag │ │
  ├────────────────┼───────────────────────────────────┼──────────┼───────────────────────────────────────────┼─────────────────┤ │
  CAVA │ UNKNOWN │ UNKNOWN │ Config generated per session by │ UNKNOWN │ │ │ │ │ player_manager.py:1107 │ │
  ├────────────────┼───────────────────────────────────┼──────────┼───────────────────────────────────────────┼─────────────────┤ │
  │ UNKNOWN; built from unpinned │ │ │ │ │ shairport-sync │ upstream source by │ UNKNOWN │ /usr/local/etc/shairport-sync.conf │
  UNKNOWN │ │ │ setup-airplay.sh │ │ │ │
  ├────────────────┼───────────────────────────────────┼──────────┼───────────────────────────────────────────┼─────────────────┤ │
  nqptp │ UNKNOWN; built from source by │ UNKNOWN │ systemd-managed │ UNKNOWN │ │ │ setup-airplay.sh │ │ │ │
  └────────────────┴───────────────────────────────────┴──────────┴───────────────────────────────────────────┴─────────────────┘

  Evidence of inability to query LXC: CLAUDE.md states "Claude Code has no SSH access to the container --- deployment is manual."
  All commands run in this session execute on the Windows/WSL2 development machine.
  ---------------------------------------------------------------------------------------------------------------------------------

3.  Verified Audio Paths

The following diagrams are CODE FACTS from repo at 72afbaf.

PATH A: LMS + bars_source="cava" (\_activate_lms_cava,
player_manager.py:542)
─────────────────────────────────────────────────────────────────────────────
LMS → squeezelite (-v flag) → snd-dummy ALSA │ └─
/dev/shm/squeezelite-`<mac>`{=html} (parallel visualiser export) │ │ │
\[cava process\] │ \[SqueezeliteShmSource\] │ method=shmem │
(best-effort, optional) │ own FFT + built-in │ read_new() → mono float32
│ conditioning │ → SustainedEnergyTracker │ → 8-bit mono bars │ →
PCM-tap onset (if !combined) │ → FIFO │ → HPSS (if enabled) │ │ ↓
\[FifoReader bg thread\] │ CavaPipeline.latest() at 30 Hz │ +
BandNormaliser (wall-clock dt) │ + OnsetDetector (30 Hz flux) │ │ │ ↓ ↓
AudioFeatures{bars, onset} SyncEngine.run() at 30 Hz from CavaPipeline
overwrites {sustained_energy, onset(multiband/superflux), HPSS}

PATH B: LMS + bars_source="pcm_pipeline" (\_activate_lms_pcm,
player_manager.py:586)
──────────────────────────────────────────────────────────────────────────────────────
LMS → squeezelite (-v) → /dev/shm/squeezelite-`<mac>`{=html} │ ↓
\[SqueezeliteShmSource owned by PcmAudioPipeline\] PcmAudioPipeline bg
thread at \~100 Hz STFT (Hamming 2048, hop=10ms) → log bars
BandNormaliser (audio-time dt = hop/sr, exact) onset:
combined/multiband/superflux at 100 Hz │ ↓ \[SyncEngine polls latest()
at 30 Hz\] AudioFeatures{bars, onset, sustained_energy=None}
\[SyncEngine.\_shm_source is None; no SustainedEnergyTracker feed\]

PATH C: AirPlay (\_activate_airplay, player_manager.py:637)
──────────────────────────────────────────────────────────── iOS/macOS →
AirPlay 2 → shairport-sync (+ nqptp PTP) → /run/huesync/airplay.pcm
(named pipe / FIFO) │ ↓ \[AirPlayPipeSource; non-blocking reads up to
65536 bytes\] assumed: S16_LE stereo 44100 Hz (AIRPLAY_SAMPLE_RATE
constant) actual: UNKNOWN (shairport-sync version/config not verified) │
PcmAudioPipeline bg thread (same as Path B) STFT, BandNormaliser
(audio-time dt), onset │ SyncEngine polls at 30 Hz AudioFeatures{bars,
onset, sustained_energy=None} \[SyncEngine.\_shm_source is None; no
SustainedEnergyTracker feed\]

  ---------------------------------------------------------------------------------------------------------------------------------
  4\. CAVA Deployment Facts
  ---------------------------------------------------------------------------------------------------------------------------------
  5\. AirPlay PCM Contract

  ┌──────────────────┬──────────────────────────────────────────┬─────────────────────────────────────────┬───────────┬─────────┐ │
  Property │ HueSync assumes │ shairport configured/default │ Deployed │ Status │ │ │ │ │ fact │ │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  │ 44100 Hz (AIRPLAY_SAMPLE_RATE constant, │ Not configured. UPSTREAM: AirPlay 2 │ │ │ │ Sample rate │ pcm_source.py:354) │
  defaults 48000 Hz; classic defaults │ UNKNOWN │ UNKNOWN │ │ │ │ 44100 Hz │ │ │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  Sample format / │ Signed (int16 = S16_LE) --- │ Not configured. UPSTREAM: AirPlay 2 │ │ │ │ signedness │ np.frombuffer(...,
  dtype=np.int16) │ defaults S32_LE; classic defaults │ UNKNOWN │ UNKNOWN │ │ │ pcm_source.py:421 │ S16_LE │ │ │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  Sample width │ 2 bytes --- n_frames = len(raw) // 4 (4 │ Not configured │ UNKNOWN │ UNKNOWN │ │ │ bytes per stereo frame = 2×S16)
  │ │ │ │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  Endianness │ Little-endian (implied by int16 on x86) │ Not configured │ UNKNOWN │ UNKNOWN │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  Channels │ Stereo, interleaved L then R --- │ Not configured │ UNKNOWN │ UNKNOWN │ │ │ samples\[0::2\], samples\[1::2\] │ │ │ │
  ├──────────────────┼──────────────────────────────────────────┼─────────────────────────────────────────┼───────────┼─────────┤ │
  Interleaving │ Interleaved (per above) │ Not configured │ UNKNOWN │ UNKNOWN │
  └──────────────────┴──────────────────────────────────────────┴─────────────────────────────────────────┴───────────┴─────────┘

  Why all are UNKNOWN: The deployed shairport-sync was built from an unpinned upstream checkout (setup-airplay.sh uses git pull
  --ff-only, no pinned tag). The exact commit/version installed is UNKNOWN. The config specifies only output_backend = "pipe" and
  pipe.name --- no format constraints. Actual output format depends on the installed version's defaults.

  The S32_LE risk: If the deployed shairport-sync uses current upstream AirPlay 2 pipe defaults (48 kHz, S32_LE),
  AirPlayPipeSource.read_new() would read 4-byte S32_LE samples as 2-byte int16 pairs. The result is not a scaled version of the
  original: the two int16 values per S32_LE sample have wildly different magnitudes and interpretations, effectively producing
  noise. This is not a silent 8.8% frequency-mapping error --- it could produce completely wrong audio data.

  The Phase 1 correction suggestion (resample_rate_request) is wrong: Codex confirms the current shairport-sync documentation uses
  output_rate, output_format, and output_channels as the correct config keys. resample_rate_request is not the correct setting. Do
  not apply blindly.

  What remains necessary to prove this: Safely determining the pipe format requires either: (a) reading shairport-sync --version on
  the LXC, (b) checking shairport-sync --options output for compiled-in defaults, (c) reading the installed source tree's version
  tag, or (d) checking the pipe output byte rate against wall clock when an AirPlay session is active --- but with strict
  constraints against adding a second FIFO reader (which would consume production stream bytes). A separate process reading the
  pipe would split the stream; this cannot be done safely in production.
  ---------------------------------------------------------------------------------------------------------------------------------

6.  LMS / Squeezelite PCM Contract

CODE FACTS from repository:

┌───────────────────────┬────────────────────────────────────────────────────────────────────────┬─────────────────────────────┐
│ Property │ Value │ Source │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Launch arguments │ -n {display_name}, -m {mac}, -o {alsa_device}, -v,
-s {lms_host} │ player_manager.py:1054-1067 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Visualiser export │ -v --- enables SHM export at
/dev/shm/squeezelite-`<mac>`{=html} │ player_manager.py:1059 │ │ flag │
│ │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ SHM path │ /dev/shm/squeezelite-{mac} │ pcm_source.py:108 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ SHM structure │ pthread_rwlock_t (56 B) + header (24 B) + buffer
(32768 B) = 32848 B │ pcm_source.py:70-84 │ │ │ total │ │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Header offset │ 56 bytes (after rwlock) │ pcm_source.py:80 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Header format │ \<IIBxxxIq (buf_size, buf_index, running, rate,
updated) │ pcm_source.py:81 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Ring buffer size │ 16384 s16 samples = 8192 stereo frames ≈ 186 ms at
44100 Hz │ pcm_source.py:67 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Buffer offset │ 80 bytes from start of shared memory │
pcm_source.py:83 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Buffer format │ Interleaved stereo s16 (int16_t) │ pcm_source.py:203 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Sample rate │ Read dynamically from SHM header at rate field │
pcm_source.py:134-136 │
├───────────────────────┼────────────────────────────────────────────────────────────────────────┼─────────────────────────────┤
│ Downmix │ (L + R) / (2 \* 32768) → mono float32 in \[-1.0, 1.0\] │
pcm_source.py:206 │
└───────────────────────┴────────────────────────────────────────────────────────────────────────┴─────────────────────────────┘

Is SHM a parallel tap or audio-from-snd-dummy? CODE FACT: The docstring
of pcm_source.py line 1-4 confirms: "Reads the same segment that cava
uses, but independently." The -v flag on squeezelite exports internal
output samples directly to SHM --- it is a visualiser tap on decoded
audio before ALSA output, not audio captured back from snd-dummy. Codex
also confirms this.

ReplayGain / volume before SHM: UPSTREAM FACT (Codex): squeezelite's SHM
exporter exports its internal output samples, and ReplayGain can be
applied during export. Whether the deployed squeezelite applies
ReplayGain is: UNKNOWN. This matters because ReplayGain would affect the
absolute level of SHM PCM but not its spectral content.

Deployment facts: squeezelite executable path, version, and whether
ReplayGain is active: UNKNOWN without LXC access.

  ---------------------------------------------------------------------------------------------------------------------------------
  7\. AudioFeatures Provenance Matrix
  ---------------------------------------------------------------------------------------------------------------------------------
  8\. EnergyProfile Input

  CODE FACT from LayerMixer.render() (sync_engine.py:1591-1607):

  if features.sustained_energy is not None: blend_input = features.sustained_energy else: \# Degraded path: no PCM source attached
  (cava-only). blend_input = features.full

  ┌───────────────────────┬──────────────────────────────────────────────────────────────┬──────────────────────────────────────┐ │
  Path │ blend_input signal │ Characteristics │
  ├───────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────┤ │
  LMS/CAVA with SHM tap │ sustained_energy --- dual-timescale log-ratio PCM RMS, │ Section-level energy; reacts over │ │ open │
  τ_short≈300ms / τ_long≈30s, mapped to \[0,1\] │ 300ms--30s timescales │
  ├───────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────┤ │
  LMS/CAVA with SHM tap │ features.full --- full-band average of exertion-normalised │ Transient-level; reacts to │ │ failed │ bars
  from CAVA │ individual beats │
  ├───────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────┤ │
  LMS/native (always) │ features.full --- full-band average of exertion-normalised │ Transient-level; reacts to │ │ │ STFT bars │
  individual beats │
  ├───────────────────────┼──────────────────────────────────────────────────────────────┼──────────────────────────────────────┤ │
  AirPlay/native │ features.full --- full-band average of exertion-normalised │ Transient-level; reacts to │ │ (always) │ STFT bars
  │ individual beats │
  └───────────────────────┴──────────────────────────────────────────────────────────────┴──────────────────────────────────────┘

  The comment in LayerMixer ("Degraded path: no PCM source attached (cava-only)") is misleading. The else branch fires for any path
  where sustained_energy is None --- which includes both the CAVA fallback AND, by design, all native paths. Native paths use
  features.full (relative exertion) as their EnergyProfile blend input permanently, not as a degraded fallback.

  This means comparing EnergyProfile behaviour between CAVA and native paths is comparing two fundamentally different input
  signals, not two analyses of the same signal.
  ---------------------------------------------------------------------------------------------------------------------------------

9.  bars_source Semantics

bars_source is a field on the Analyser entity with two defined values:
"cava" (default) and "pcm_pipeline".

It controls the analysis backend only for LMS players. The activation
branch in \_activate_lms() (player_manager.py:518-521) reads
profile.bars_source and calls either \_activate_lms_cava() or
\_activate_lms_pcm().

For AirPlay players, activate_coupling() (player_manager.py:490-497)
branches on player.type == VirtualPlayerType.AIRPLAY before inspecting
bars_source. AirPlay always calls \_activate_airplay(), which always
creates PcmAudioPipeline(AirPlayPipeSource). The bars_source field on
the linked Analyser is not read.

bars_source = "pcm_pipeline" therefore means: "for this LMS player,
bypass cava and run PcmAudioPipeline directly on the squeezelite SHM."
It has no effect on AirPlay sessions.

No other runtime paths use this field.

  ------------------------------------------
          10\. PcmSource Boundary Assessment
  ------------------------------------------
                    11\. Timing Verification

          BandNormaliser 30 Hz vs 100 Hz ---
                          Corrected Analysis

    The Phase 1 audit claimed BandNormaliser
    time constants differ by \~3× between 30
       Hz (CAVA path) and 100 Hz (native PCM
         path). This claim is mathematically
     incorrect. The Codex review is correct.

          For alpha = 1 - exp(-dt/tau), with
     constant input x, after elapsed time T:

       E(T) - x = (E(0) - x) · exp(-T / tau)

   This is independent of call frequency. At
     T = 1 second with tau = 700 ms: - At 30
  Hz: 30 calls, each alpha = 1 - exp(-1/30 /
  0.7) ≈ 0.04650; residual = (1-0.04650)\^30
     = exp(-1/0.7) ≈ 0.2397 - At 100 Hz: 100
  calls, each alpha = 1 - exp(-0.01 / 0.7) ≈
      0.01418; residual = (1-0.01418)\^100 =
                        exp(-1/0.7) ≈ 0.2397

    The steady-state exponential response is
   identical. Per-call alpha differs; number
               of calls compensates exactly.

         Real remaining differences (not the
                                claimed 3×):

    Difference: Transient sampling LMS/CAVA:
           One call covers \~33 ms of audio;
  transients narrower than 33 ms are sampled
    at most once Native PCM: One call covers
   10 ms; narrower transients may be sampled
     multiple times Impact: PCM path samples
         more transient detail at high rates
    ────────────────────────────────────────
            Difference: Frame loss LMS/CAVA:
   CavaPipeline: latest frame only; CAVA may
  produce 60 fps → \~2 CAVA frames discarded
             per SyncEngine tick Native PCM:
       PcmAudioPipeline: normalises all STFT
               frames at 100 Hz; only latest
            AudioFeatures slot used at 30 Hz
  SyncEngine poll Impact: PCM BandNormaliser
       EMA evolves fully at 100 Hz; only the
         final state is exposed to rendering
    ────────────────────────────────────────
  Difference: Attack phase at very short tau
   LMS/CAVA: At 30 Hz, tau \< dt (\~33 ms) →
                      alpha approaches 1.0 →
   near-sample-and-hold for one call. At 100
  Hz, tau \< 10 ms behaves similarly. Effect
        is meaningful only for tau \<\< call
            interval Native PCM: Impact: For
   tau_attack = 5 ms at 30 Hz, alpha ≈ 0.999
       --- one-step jump. At 100 Hz, alpha ≈
    0.865 --- \~2 frames to track. This is a
   real difference for the attack phase only
    ────────────────────────────────────────
           Difference: EMA uses old baseline
   LMS/CAVA: First-call seeding: EMA = first
     frame; delta = 0; output = 85 uniformly
        (CODE FACT: sync_engine.py:213-246).
         Subsequent calls: exertion measured
     against pre-update EMA Native PCM: Same
  Impact: Attack-step response is one-sided;
      the claimed "first-call-dt distortion"
    (Phase 1) is incorrect (Codex confirmed:
            seeding prevents any distortion)
    ────────────────────────────────────────
          Difference: update phase LMS/CAVA:
    Wall-clock dt varies with asyncio jitter
   Native PCM: Audio-time dt is constant (10
              ms exact) Impact: PCM path has
      deterministic EMA evolution; CAVA path
                                    does not

              SustainedEnergyTracker timing:

    \- Code: runs inside SyncEngine.run() at
    each 30 Hz tick when \_shm_source is not
   None - Uses wall-clock dt: dt = (tick_t -
   self.\_last_tick_t) if self.\_last_tick_t
          is not None else SEND_INTERVAL_S -
     tau_short = 300 ms, tau_long = 30 s ---
        these are much longer than the 30 Hz
  jitter of tens of milliseconds; jitter has
             negligible effect on these time
   constants - STATUS: Wall-clock timing for
    SustainedEnergyTracker: does not distort
                       meaningful EMA values

                      Stale frame behaviour:

       \- CAVA path: FifoReader keeps latest
      frame only. If SyncEngine polls faster
         than CAVA writes, the same frame is
    re-read. CavaPipeline.latest() is called
      with a new wall-clock dt each time, so
     normalise() is called multiple times on
     the same frame with different dt values
     --- the EMA advances in wall-clock time
               even without new audio. Code:
  sync_engine.py:776-803. - Native PCM path:
    SyncEngine.run() calls analyser.latest()
    which reads a pre-computed AudioFeatures
           slot (set in \_run() thread). The
   BandNormaliser has already run at 100 Hz;
        SyncEngine only reads the result. No
         repeated normalise() calls on stale
          data. - This is an asymmetry: CAVA
    BandNormaliser can advance during source
         silence; native BandNormaliser only
               advances when samples arrive.
  ------------------------------------------

12. Multiple-Consumer / Buffering Findings

Squeezelite SHM (SqueezeliteShmSource)

CODE FACTS from pcm_source.py:87-208:

-   Each SqueezeliteShmSource instance has its own \_prev_index ---
    independent read cursors.
-   Multiple instances can open the same SHM segment simultaneously
    without stealing each other's samples.
-   However: the lock pthread_rwlock_t at offset 0 is NOT taken by
    HueSync. Taking a read lock can cause squeezelite to skip exporting
    blocks; HueSync deliberately avoids this. The seqlock-style
    consistency check is not a true sequence lock: an unchanged
    buf_index_after == buf_index cannot prove the writer was inactive
    during the copy (doc: pcm_source.py:189-201).
-   Lost samples: when torn-read is detected, \_prev_index has already
    advanced and the discarded block is simply dropped. No discontinuity
    signal.
-   Ring capacity: 8192 stereo frames ≈ 186 ms at 44100 Hz.
-   Lap detection: (buf_index - prev_index) % VIS_BUF_SIZE cannot detect
    a complete lap. If exactly 16384 samples are written between reads,
    the result is zero (appears as "no new samples"). The half-ring cap
    handles partial laps but not complete ones.

CAVA vs HueSync SHM reads --- same ordered samples?

No. UPSTREAM FACT (Codex): CAVA 0.10.7's SHM input copies fixed ring
locations without reconstructing the chronological stream from
buf_index. Its sleep calculation merits investigation. HueSync's
SqueezeliteShmSource does reconstruct from the write-position delta.
Even if both read the same physical memory, the sample windows extracted
may overlap, skip, or be misaligned relative to each other. "Both read
the same SHM" does not mean "both receive the same ordered PCM stream."
This directly undermines the proposed same-PCM comparison as a
source-elimination experiment. (Behaviour of deployed CAVA 0.10.7:
UNKNOWN; upstream behaviour per Codex.)

AirPlay FIFO (/run/huesync/airplay.pcm)

This is a named FIFO (kernel pipe), not a broadcast mechanism. Any
second process opening it for reading becomes a second reader and will
consume a portion of the byte stream, starving the production reader.
The bytes that one reader consumes are unavailable to the other. Two
simultaneous readers each receive approximately half the audio stream.

Consequence: No diagnostic process can safely read the AirPlay pipe
while HueSync is actively using it. This is why AirPlay format
verification cannot be done read-only without disrupting the production
stream.

CAVA output FIFO (session.fifo_path)

Same FIFO semantics as the AirPlay pipe. Attaching a second FifoReader
or cat to this FIFO would split the CAVA bar stream. Not safe for
production-concurrent inspection.

  ----------------------------------------------------------------------------------------------------------------------------------
  13\. Corrections to DSP Phase 1 Audit
  ----------------------------------------------------------------------------------------------------------------------------------
  14\. Remaining Unknowns

  ┌───────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────┐ │
  Unknown │ Minimum safe observation to resolve │
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤ │
  Deployed shairport-sync version │ On LXC: shairport-sync --version and review /usr/local/etc/shairport-sync.conf --- │ │ and
  AirPlay 2 pipe format (rate, │ read-only, zero disruption │ │ bit width) │ │
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤ │
  │ On LXC when NOT streaming: stat /run/huesync/airplay.pcm to confirm it exists; measure │ │ Whether deployed shairport-sync │
  pipe byte rate by counting bytes written in 5 s during an active AirPlay session using a │ │ outputs S16_LE or S32_LE │ process
  that does NOT open the FIFO for reading (e.g. monitor the process's fd stats │ │ │ via /proc) │
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤ │
  Deployed CAVA version and whether │ │ │ autosensitivity / │ On LXC: cava --version; read /tmp/huesync/\*.conf for an active
  session │ │ noise_reduction are active at │ │ │ their defaults │ │ │ Deployed CAVA SHM reader behaviour --- │ On LXC: cava
  --version to confirm 0.10.7; upstream source review then applies │ │ same as upstream 0.10.7 or different │ │
  ├───────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤ │
  Deployed squeezelite version and │ │ │ whether ReplayGain is applied to SHM │ On LXC: squeezelite --version; squeezelite -v flag
  documentation/source │ │ export │ │
  ├───────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤ │
  Whether SHM tap reliably opens in │ Review HueSync logs on LXC: grep for "PCM tap SHM source opened" and "Could not open │ │
  production LMS/CAVA sessions │ squeezelite SHM" in journalctl -u huesync │
  ├───────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤ │
  Whether CAVA produces 60 fps or fewer │ Instrument FifoReader with a frame counter; or add logging to CavaPipeline (not in │ │ in
  practice, and how many frames │ scope for this task) │ │ FifoReader discards │ │
  ├───────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤ │
  Nqptp version and whether it │ │ │ successfully provides PTP for AirPlay │ On LXC: systemctl status nqptp; nqptp --version if
  available │ │ 2 on the deployed LXC │ │
  ├───────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤ │
  Whether the SHM ring lap detection │ │ │ failure (full 16384-sample lap │ Add a lap-detection counter to
  SqueezeliteShmSource.read_new() --- requires a code │ │ appearing as zero new samples) ever │ change; or observe via periodic
  logging of n_new values │ │ occurs in practice │ │
  └───────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┘
  ----------------------------------------------------------------------------------------------------------------------------------

15. Preconditions for Phase 2

Before designing the controlled same-PCM CAVA-vs-native experiment,
these facts must be established:

1.  AirPlay pipe PCM format (rate and bit width). If S32_LE, HueSync is
    currently parsing the AirPlay pipe incorrectly; this must be fixed
    before the experiment. Minimum: shairport-sync --version on LXC and
    review of effective defaults for that version.
2.  Whether CAVA and HueSync SHM readers receive the same ordered
    samples. The Codex raises a credible concern that CAVA's SHM reader
    may not reconstruct samples in the same chronological order as
    HueSync's SqueezeliteShmSource. Without this verified, "same SHM" is
    not the same as "same input to both analysers." Minimum: inspect the
    deployed CAVA 0.10.7 SHM reader source against SqueezeliteShmSource
    to confirm or quantify the ordering difference.
3.  What stereo treatment CAVA applies. CAVA analyses L and R separately
    then averages bars. HueSync sums L+R before FFT. A controlled
    experiment must account for this or use mono content. Minimum:
    confirm the deployed CAVA version matches the upstream 0.10.7
    behaviour described by Codex.
4.  Whether the EnergyProfile comparison is meaningful at all given that
    native paths use features.full (transient detector) as blend input
    while CAVA uses sustained_energy (section-level detector). These are
    fundamentally different signals; any comparison of EnergyProfile
    behaviour must acknowledge this asymmetry.
5.  Whether compare_bars.py's sampling approach (once per second, latest
    values) captures the phenomenon of interest. The script captures a
    snapshot per second and computes cosine similarity. It does not
    measure temporal jitter per bar, frame loss, or onset timing. Phase
    2 experiment design must decide whether this resolution is
    sufficient.

  ----------------------
  16\. Recommendation

  NOT READY ---
  DEPLOYMENT FACTS STILL
  MISSING

  Primary reason: The
  AirPlay pipe format
  (sample rate and bit
  width) is unverified.
  If the deployed
  shairport-sync outputs
  S32_LE at 48 kHz
  (current upstream
  AirPlay 2 defaults)
  while HueSync reads
  int16 at 44100 Hz, the
  AirPlay path is
  producing incorrect
  analysis silently.
  This must be confirmed
  or refuted before any
  experiment involving
  AirPlay audio can be
  considered valid.

  Secondary reason: The
  CAVA SHM reader
  ordering behaviour is
  uncertain. The Codex
  identifies that
  upstream CAVA 0.10.7
  may not reconstruct
  samples in
  chronological order
  from buf_index. Until
  this is confirmed
  against the deployed
  CAVA binary, the
  compare_bars.py
  experiment does not
  have provably
  identical PCM inputs
  to both analysers ---
  which was the stated
  goal.

  What needs to happen
  first:

  1\. On LXC, read-only:
  shairport-sync
  --version, cava
  --version, squeezelite
  --version, systemctl
  is-active for all
  services, and cat
  /tmp/huesync/\*.conf
  (active cava config).
  These five commands
  resolve most
  deployment unknowns.
  2. Determine the
  actual AirPlay pipe
  format for the
  deployed
  shairport-sync
  version. 3. Confirm
  whether the pipe
  format matches
  HueSync's hardcoded
  assumption, and if
  not, determine the
  correct config keys to
  enforce the expected
  format before
  proceeding.

  Once those facts are
  in hand, Phase 2
  experiment design can
  be finalised with
  known inputs on both
  sides.
  ----------------------

Report produced by code review of repository at commit 72afbaf. No files
were modified, no services were touched, no processes were started or
stopped. All deployment-specific facts (running services, installed
versions, effective configurations) are marked UNKNOWN due to absence of
LXC access from the development environment.
