# LampaStream — "No onset missed": research and design for the event pipeline

Date: 2026-10-25. Starting commit for implementation: `e03f1a8` (REG-01 merged).
Companion to `docs/baseline.md` (phase-1 regression numbers) and the development plan tickets `TIME-01`, `EVENT-01`, `RENDER-01`.

## 0. The problem, measured

REG-01 pins the following for every click fixture, both routes, 30 and 60 Hz, default config:

| quantity | value today |
|---|---|
| onset events detected by the analyser | 19 of 19 clicks (clicks-120) |
| events that reach a rendered, sent scene | **0** |
| availability − true onset | +5 hops (≈ 50 ms) |
| candidate position − true onset | −3 hops (window start, not peak) |
| reported strength vs candidate-frame strength (combined) | 16.7 vs 271.9; bass/mid report 0 |
| silence trains the picker's normaliser | yes (EMA → 1e-24, spurious onset on resume) |

Three independent causes, all in `src/lampastream/sync_engine.py`:

1. **Transport.** `CanonicalAnalysisPipeline` publishes ~100 snapshots/s. It keeps both a lossless bounded queue (`drain_publications()`, maxlen 1000, drop counter) and a `latest()` snapshot. The normal route (`SyncEngine.run`, ~line 3210) reads only `latest()` at 30 Hz, so onset flags on the ~7 of 10 intermediate snapshots are never seen. The timestamped route drains the queue (good) but `SceneSchedule.due()` sends only the newest due scene; the rendered flash scenes in between are discarded.
2. **Representation.** An onset is a boolean on a 10 ms `AudioFeatures` snapshot. Renderers test `features.onset` at render time and add brightness *for that one tick* (`_clip_and_flash`, `_SpectrumRgbRenderer`). The `flashes` renderer has an envelope, but its `_cooldown = 4` and `*= (1 - decay*2)` are per tick, so a 20 Hz and a 60 Hz loop produce different light.
3. **Detector contract.** `OnsetDetector.process()` (Dixon 2006, `ci = M*W = 9`, buffer 13) confirms a candidate 3 frames after it occurred and `return True, flux` returns the *current* frame's flux, not `f_c`. `BeatDetector._parse_onset_frame` then stamps the result on the current hop. Normalisation (EMA mean/std) is updated in silence.

Also: in the default configuration (`effect_type: spectrum_rgb`, `onset_flash_intensity: 0.0`) an onset has no visible effect at all.

## 1. What the literature says about the detector

Full citations in §5. Key numbers:

- **Lookahead buys almost nothing for flux-type ODFs.** Böck, Krebs & Schedl (ISMIR 2012) ran the Dixon-style picker online with `w2 = w4 = 0` (no future frames), `w1 = 3` (30 ms past max), `w3 = 40–120 ms` past mean, `w5 = 30 ms` min distance, and lost only ≈ 0.25 % F-measure versus the offline picker with 3 future frames. Online detections came out ~1 frame early, so they add +10 ms. Smoothing and global normalisation are "unusable online".
- **madmom's online peak picker reports the candidate frame, not the current one** (`process_online` counter arithmetic), with `post_max = post_avg = 0`, `combine = 30 ms`; `delay ≠ 0` is an error online. librosa's `peak_pick` has the same three conditions; `post_max = 1` means "no future".
- **SuperFlux (Böck & Widmer, DAFx 2013)**: log-filtered magnitude (24 bands/octave, 27.5 Hz–16 kHz), `log10(λX+1)`, 3-bin maximum filter over frequency on the previous frame before differencing, half-wave rectified sum. Online = offline with `post_max = post_avg = 0`; F 0.820 vs 0.836. Log-filtered flux beats raw spectral flux online by ~4 F-points (80.3 vs 76.1) — band grouping + log compression is the biggest single win.
- **Silence-proof thresholds**: an absolute floor `δ_abs` in un-normalised units (librosa `delta`, madmom `threshold`, Essentia `threshold 0.05`) **plus** a relative/ratio test (Essentia `ratioThreshold`, novelty / local mean); log compression makes δ scale-independent; aubio discards onsets whose input block is below `silence` (−70 dBFS default, −90 "keep everything"). Adaptive statistics must not learn from gated frames.
- **Min inter-onset interval**: 20–50 ms everywhere (aubio 12/20/50 ms, madmom 30 ms, Essentia 20 ms, Böck 30 ms). 16th-note hats at 174 BPM are 86 ms apart, so 30 ms is safe.
- **Per-band merge** (Thoshkahna & Ramakrishnan 2009; Klapuri 1999): per-band detection, vote/merge within 50 ms, keep the loudest; event carries the set of bands that fired. Vogl et al. 2018 (drum transcription) pick peaks per instrument with 20 ms windows and δ ≈ 0.1–0.2.
- **Neural detectors**: madmom's online RNN (OnsetDetector.LL) is causal and cheap (3×20-unit RNN; real-time on 2009 hardware; F 0.817 online) but the models are CC BY-NC-SA and the code is unmaintained; CNN variants carry 70 ms lookahead. Not for this ticket; a candidate for later if recall on quiet material proves limiting.
- **Beat tracking for anticipation** (BTrack GPL — excluded; madmom DBN online CC BY-NC-SA models; RNN-PLP-On, TISMIR 2024, 11.6 ms latency, 30–240 BPM): useful later to pre-arm on-beat kicks; ~75 % F1 on mixed sets, unmeasured on EDM. Not this ticket.

### Perception: how much latency is allowed, how long must a flash be

- Light *late* is the costly direction. Detectability of audio-leading (= light-late) offsets: ITU-R BT.1359 +45 ms; ATSC +15 ms; flash-beep temporal binding window ≈ 80–100 ms; point of subjective simultaneity is 19–37 ms on the *visual-leading* side. So a flash 20–40 ms **before** the sound reads as simultaneous; 45–100 ms **after** is noticed.
- Minimum visible flash: cone integration ≈ 20–30 ms; brightness appears maximal at 50–100 ms (Broca–Sulzer). On a 25 Hz lamp a hit must survive **≥ 2 lamp frames (80 ms)** at or near peak to be seen as a hit rather than a flicker.

## 2. Detector design (TIME-01)

Keep the existing processors and the `AudioFeatures` contract; change the picker contract and the normaliser, add an event record.

- **Candidate attribution.** The picker reports `(candidate_frame, candidate_strength = f(candidate))` and the confirmation frame separately. In Dixon terms: onset at frame `n − w`, strength `f(n − w)`, availability `n`. In hops, both at 48 kHz and after resampling at 24 kHz; the 8-hop constant that REG-01 measured at 48 kHz must become an explicit, sample-rate-independent `lookahead_frames` field.
- **Lookahead `post_max` configurable 0–3 frames, default 1.** Böck: 0 costs ≤ 0.25 % F; 1 frame removes most rising-edge double hits on slow attacks for +10 ms. Default 1; 0 for the "fast" style later.
- **Three conditions, causal form**: `f(n) ≥ max(f(n−3…n+post_max))`; `f(n) ≥ mean(f(n−10…n)) + δ` with `δ = max(δ_rel·std, δ_abs)`; `n − last ≥ min_ioi` (30 ms default, per band). Drop Dixon's α-decay as a hard condition; keep `α` as a soft confidence term so existing `onset_alpha` settings still mean something.
- **Silence-proof normalisation**: freeze EMA mean/std when frame RMS < gate (−60 dBFS default; expose) and during an emitted event; `std ≥ std_floor`; on un-gating hold statistics for 2–3 frames so the first transient is judged against pre-silence statistics.
- **Per-band merge**: band pickers (bass/mid/treble, existing `multiband` split) emit candidates; a 30 ms combine window keyed to the earliest candidate frame yields one event with `bands` set, `dominant_band`, `strength = max normalised band flux` (clipped at z = 6 → 0..1) and `confidence` = margin above threshold × bands-fired vote. The combined (`StftOnsetPipeline`) and `superflux` methods produce single-band events the same way.
- **Event record** (`OnsetEvent`, new in `types.py`): `id` (epoch, band, candidate_sample), `epoch`, `candidate_sample`, `availability_sample`, `lookahead_frames`, `strength` 0..1, `strength_raw`, `confidence` 0..1, `bands`, `dominant_band`, `play_monotonic | None` (filled on the timestamped route). `AudioFeatures.onset*` fields stay and are derived from the events in the interval (compatibility; the web UI and REG pins read them).
- **Expected latency** true onset → event available: hop 0–10 + peak-vs-onset ≈ 10 + post_max 10 + compute 1–2 ≈ **20–30 ms**, versus ≈ 50 ms today.

## 3. Event pipeline design (EVENT-01), output-agnostic

Principles, each traceable to §4: timestamped event queue drained to `now + lead` (Music Assistant Hue provider); envelope anchored at the event's own time, not the drain time (MA); max-merge of a burst within one drain, count kept separately (MA); min-IOI in the detector, never in the consumer (madmom, aubio); hold ≥ one output frame so a slow output cannot sample past the hit (WLED's `max(50 ms, frametime)`, TouchDesigner "Peak Length"); continuous features stay latest-value with their own attack/release, events go through the queue only (WLED's deprecated `binNum/maxVol` path shows what happens when they are mixed).

1. **Event queue beside the publication queue.** `CanonicalAnalysisPipeline` gets `drain_events() -> list[OnsetEvent]` (bounded, drop-counted, same lock discipline as `drain_publications()`). Publications stay as they are; `AudioFeatures.onset*` remain derived flags for compatibility.
2. **One intake for both routes.** `SyncEngine.run` drains *all* events every tick on both routes (the normal route stops relying on `latest()` for events; `latest()` keeps serving the continuous features). Each event gets an availability time (`clock()` at drain) and, on the timestamped route, `play_monotonic` from the record it belongs to. Counters per band: received, merged, triggered, expired (`now − t_event > max_age`), lost (must be 0 by construction; assert in tests).
3. **`OutputCapabilities`** on the `Output` protocol: `update_hz`, `colour_depth_bits`, `transport_latency_s` (estimate), `min_visible_hold_s` (default `2 / update_hz`), `supports_per_channel_timing`. `HueDriver` reports 25 Hz, 8 bit, ~0.02 s. The trace output reports whatever its room file says. Nothing in `sync_engine.py` or a renderer may reference Hue; future WLED/DDP (60–100 Hz), LIFX, Nanoleaf, Art-Net/DMX drivers fill in their own numbers and the rest of the chain is unchanged. The per-lamp output profile (Iris floor/dim exponent, from the earlier research) also lives behind this protocol.
4. **`TriggerEnvelope` per band (+ "all")**, time-based: `trigger(strength, t_event, policy)`; `value(t)` = `peak` while `t − t_event < hold`, then exponential decay with `release_s`; `hold = max(effect.onset_hold_s, capabilities.min_visible_hold_s)`. Re-trigger policies as TouchDesigner: *restart*, *ignore-during-hold*, *add-with-clamp*; default *restart* with max-merge. Anchored at `t_event` so a late render tick shortens the visible flash but never shifts its phase; on the timestamped route `t_event` is the play time, so the envelope can be evaluated for the scene's play time exactly.
5. **Renderers read the envelope, not a boolean.** `AudioFeatures` as seen by renderers gets `onset_envelope`, `onset_envelope_bass/mid/treble` (0..1), `onset_count_since_render` (for seeders: splotches, fireworks, palette steps), `onset_age_s`, `onset_strength` = candidate strength of the newest event. `features.onset` becomes "≥ 1 event since the previous render" (latched, lossless), so untouched renderers get strictly better behaviour; the flash renderers (`_clip_and_flash`, spectrum_rgb/band_colours flash, `flashes`, `pulses`) switch to `intensity × envelope` and lose their per-tick cooldowns/decays. Everything else per-tick stays for RENDER-01.
6. **Lead and offset.** `lead_s` (default 0.02, MA's figure; measured later by PHYS-01) is applied on the timestamped route; on the live route a user-facing "visual offset" cannot delay audio, so the only knob is how early the event is known (TIME-01's 20–30 ms).
7. **Quantisation guard** at the output: a trigger must lift the output by ≥ 8 LSB over the running baseline on an 8-bit output, and the decay step per output frame must be ≥ 1 LSB or be held — otherwise an Iris shows a stuck tail. Expressed in terms of `colour_depth_bits`, not 255.

Expected result on the click fixtures: received 19 → triggered 19, lost 0, each visible for ≥ 80 ms on a 25 Hz output, phase error ≤ one render tick, both routes, 20–60 Hz.

## 4. Competitor and library practice for event transport and envelopes

Code read at HEAD on 2026-10-25 (repos: wled/WLED, LedFx/LedFx, aubio/aubio, CPJKU/madmom, adamstark/BTrack, hyperion-project/hyperion.ng, awawa-dev/HyperHDR, music-assistant/server, Sendspin/aiosendspin, FastLED/FastLED, keijiro/Lasp, CalcProgrammer1/KeyboardVisualizer). Principles reused; no GPL code is copied (BTrack is GPL-3).

| Project | Transport | Lossless? | Event → light | Timestamp awareness |
|---|---|---|---|---|
| **Music Assistant** `providers/hue_entertainment/analyzer.py` (Apache-2.0) | `_pending_peaks` deque of `(ts, boost)`, drained in `_consume_peaks(now_us)` up to `server_now + hue_latency` (default 20 ms); 30 Hz Hue render, 20 Hz analysis | yes, count and strength | boost = strength × 0.3, **linear decay 250 ms anchored at the event's own `ts`**; bursts max-merged, palette walker advances per event | yes — server clock; beats pre-scheduled with ±8 % triangle window |
| **aiosendspin** `features.py` (MA's producer) | per-chunk `peak` 0–255 with 80 ms min-IOI, energy > 1.6 × EMA, fast EMA attack | — | — | authors' TODO: "onset detection runs only at the periodic hop … decouple to run per audio chunk" — the same throttling bug |
| **MA WLED provider** | sticky `_peak_pending` OR-ed across due frames, cleared after send | existence only | WLED side | yes |
| **WLED audioreactive** (`audio_reactive.cpp`) | `samplePeak` latch auto-reset after `max(50 ms, frametime)`; `udpSamplePeak` reset-on-send | existence; two peaks in one hold merge | effects restart a ripple/puddle on the flag, `fade_out` per frame; 100 ms min-IOI | wall clock, not exposed |
| **LedFx** | three patterns in one codebase: latest-wins `beat_now` (lossy, `energy.py`), producer-side accumulator (`power.py` sparks, lossless), `queue.Queue` popped one per render (`real_strobe.py`, lossless but smears bursts); beat oscillator = continuous sawtooth phase | mixed | `ExpFilter(alpha_decay, alpha_rise)`; `*= decay_rate` per audio frame | Sendspin route schedules the *audio* to play time (5 ms granularity); aubio's `get_delay_s` is not used |
| **aubio** `onset.c` | per-hop flag; `aubio_onset_get_last()` = `last_onset − delay`, `delay = 4.3·hop` default | caller must consume every hop | `minioi` 50 ms; `silence` −70 dB gate | **backdates** by the detector delay; sub-hop quadratic peak position |
| **madmom** `OnsetPeakPickingProcessor(online=True)` | returns a list of onset times per chunk; `combine 30 ms` carried across chunks | yes | — | reports the candidate frame (`counter + index`); `post_* = 0`; `delay` unsupported online |
| **HyperHDR** | `_resultIndex` sequence counter; effect diffs it, interpolates between analysis frames | spectrum only, no events | peak-hold with accelerating decay (`deltas × 1.5`) | none |
| **Hyperion.ng** | VU image, latest wins | no events | — | none |
| **BTrack** (GPL) | `beatDueInFrame` flag cleared each hop; beat *predicted* half a period ahead | lossy unless latched | — | scheduled: `timeToNextBeat` known in advance |
| **FastLED `fl::AudioReactive`** | `isBeat()` latest-wins; new API `onBeat(callback)` draws into the LED buffer while draining every 1 ms | callback path lossless | `BEAT_COOLDOWN 100 ms`; attack/decay factors | none |
| **Keijiro LASP** (Unity) | RMS over *all audio since the last frame*; instant rise, accelerating fall | yes by construction | hold-and-fall | none |
| **TouchDesigner Trigger CHOP** | — | — | full ADSR: Re-Trigger Delay, Min Trigger Length, Attack, **Peak Length (hold)**, Decay, Sustain, Release; re-trigger policy *Ignore During Attack / Add / Restart* | — |
| **Resolume** FFT animation, **KeyboardVisualizer** (OpenRGB) | value-only peak-hold | — | Fall / multiplicative decay | — |
| **Hue Sync app, Nanoleaf Rhythm, Razer, iCUE, Govee, SoundSwitch** | no technical disclosure found; Hue Sync + Spotify uses pre-analysed scripts ("zero lag"); SoundSwitch real-time BPM for Autoloops | — | Hue Sync: one Intensity slider | — |

Note on Hue rates: "25 Hz per lamp, 50–60 Hz stream" could not be confirmed from an official Signify page; third-party sources say "up to 25 updates per second" (HueLibEnt) and "~30 Hz comfortable" (Music Assistant). Treat the output rate as a capability to measure (PHYS-01), not a constant.

Lossy anti-pattern, seen four times (LedFx `energy.py`, FastLED `isBeat()`, BTrack flag, aubio flag when polled): a per-frame boolean overwritten every hop and polled by a slower consumer. That is LampaStream's normal route today.

## 5. Sources

Competitor/library code: see §4 table (repos cloned at HEAD 2026-10-25). Web: https://www.music-assistant.io/plugins/hue-entertainment/ ; https://github.com/daniel1111/HueLibEnt ; https://developers.meethue.com/?p=3403 ; https://www.philips-hue.com/en-ca/explore-hue/blog/sync-with-music ; https://docs.derivative.ca/Trigger_CHOP ; https://resolume.com/support/en/6/parameter-animation ; https://essentia.upf.edu/reference/streaming_SuperFluxPeaks.html

Papers and library docs:

- Böck, Krebs, Schedl 2012, "Evaluating the online capabilities of onset detection methods", ISMIR — https://archives.ismir.net/ismir2012/paper/000049.pdf
- Böck, Arzt, Krebs, Schedl 2012, "Online real-time onset detection with recurrent neural networks", DAFx — https://www.dafx.de/paper-archive/2012/papers/dafx12_submission_4.pdf
- Böck & Widmer 2013, "Maximum filter vibrato suppression for onset detection" (SuperFlux), DAFx — https://dafx.de/paper-archive/2013/papers/09.dafx2013_submission_12.pdf
- Dixon 2006, "Onset detection revisited", DAFx — https://dafx.de/paper-archive/2006/papers/p_133.pdf
- Bello et al. 2005, "A tutorial on onset detection in music signals" — https://www.cs.bu.edu/fac/snyder/cs583/Literature%20and%20Resources/bello_onset_tutorial.pdf
- madmom onsets (source v0.15) — https://madmom.readthedocs.io/en/v0.15/_modules/madmom/features/onsets.html ; docs v0.16 — https://madmom.readthedocs.io/en/v0.16/modules/features/onsets.html ; beats — https://madmom.readthedocs.io/en/v0.16/modules/features/beats.html ; licence — https://pypi.org/project/madmom
- librosa onset — https://librosa.org/doc/main/_modules/librosa/onset.html ; peak_pick — https://librosa.org/doc/main/generated/librosa.util.peak_pick.html
- Essentia SuperFluxExtractor — https://essentia.upf.edu/reference/std_SuperFluxExtractor.html
- aubio(1) — https://manpages.debian.org/testing/aubio-tools/aubio.1 ; aubioonset(1) — https://aubio.org/manpages/latest/aubioonset.1.html ; onset.h — https://aubio.org/doc/latest/onset_8h_source.html
- Thoshkahna & Ramakrishnan 2009, psychoacoustic multiband onset detection — https://www.scitepress.org/Papers/2009/22384/22384.pdf
- Vogl et al. 2018, multi-instrument drum transcription — https://ar5iv.arxiv.org/html/1806.06676
- Gong & Serra 2018, efficient DL onset model — https://arxiv.org/pdf/1806.06773
- BeatNet — https://arxiv.org/pdf/2108.03576 ; Beat This! — https://ismir2024program.ismir.net/poster_10.html ; Meier, Chiu, Müller 2024 (RNN-PLP online) — https://transactions.ismir.net/articles/189 ; BTrack — https://code.soundsoftware.ac.uk/hg/btrack/file/1.0.0/README.md
- A/V sync standards — https://en.wikipedia.org/wiki/Audio-to-video_synchronization ; AV desync in sports video — https://arxiv.org/pdf/2212.01686 ; Chen et al. 2016 flash-beep simultaneity — https://mail.maurer.ca/dpubs/Chen.pdf ; temporal binding window review 2023 — https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2023.1067632/pdf ; temporal vision (NCBI Bookshelf) — https://ncbi.nlm.nih.gov/books/NBK11559/pdf/Bookshelf_NBK11559.pdf
