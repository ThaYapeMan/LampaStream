# How the competition makes lights flash on the beat — code analysis

Date: 2026-10-27. Sources: repositories cloned at HEAD on 2026-10-25 (LedFx/LedFx, music-assistant/server + Sendspin/aiosendspin, wled/WLED, FastLED/FastLED, aubio, madmom); every statement below points at a file and line. Purpose: decide what LampaStream's beat trigger and beat rendering should be after the EVENT-01 … PREVIEW-01 work showed the lamps "always on, no distinct flashes" on real music.

## 0. What the deployed LampaStream does today, for contrast

- Trigger: spectral flux summed over all 1025 bins (plus short-window variants), Dixon-style peak picking, 30 ms min-IOI, no level AGC; every hat, snare, kick and texture change is an event. Measured: 80 events / 10 s on pink noise, 303 / 20 s on a sine sweep (docs/baseline.md).
- Rendering: accent lift of 35 % *toward the channel's own full value* on top of the effect's base colour, hold 80 ms, release 250 ms. On a base that is already bright that is a step of a few percent; with events every 100–200 ms the envelopes overlap into a constant lift.
- Knobs: Analyser (method, delta, alpha, lookahead, floor, min-IOI, silence gate …), Effect (mode, amount, band weights, curve, spatial, hold, release, retrigger, lead …).

## 1. The triggers, side by side

| Project | Signal | Level handling (AGC) | Rule | Dead time | File:line |
|---|---|---|---|---|---|
| **LedFx** `volume_beat_now` | sum of mel bands below 100 Hz ("beat" band; `freq_max_mels = [100, 250, 3000, 10000]`) | melbank divided by `mel_gain` = ExpFilter(rise 0.99, decay 0.01) of its own max, then smoothed; volume gate `min_volume` | `beat_power × N / sum(history 200 ms) − 1 ≥ 0.5` AND `max(melbank) ≥ 0.5` | 0.1 s | `ledfx/effects/audio.py:1134-1139, 1207-1224, 1276-1300`; `melbank.py:325-348` |
| **Music Assistant / aiosendspin** `_detect_onset` | A-weighted **broadband** energy per chunk | EMA 0.9/0.1 normal, **0.6/0.4 right after a peak** ("fast attack so we don't keep firing on a sustained rise") | `energy > 1.6 × ema`; strength = clip((energy/ema − 1.6)/6) | 80 ms | `aiosendspin/server/roles/visualizer/features.py:515-546` |
| **WLED** audioreactive | one FFT bin chosen by slider (`binNum`, default 8), `valFFT` after AGC | PI-controlled AGC: setpoints 40–65 % and 85 % of full scale, fast follow ≈ 0.15 s, slow 2–15 s, presets normal/vivid/lazy | `valFFT[binNum] > maxVol` (slider) and `sampleAvg > 1` | 100 ms | `usermods/audioreactive/audio_reactive.cpp:124-125, 194-203, 734-744`; `wled00/FX.cpp:6734-6735` |
| **FastLED** `detector::Beat` | half-wave-rectified flux over the **lower 8 of 16 CQ bins** (≈ 24–650 Hz), linear magnitude | none in the loop (the WLED-derived `AutoGain` class exists but is not wired in) | `flux > max(1.3 × mean(flux, last 43 frames ≈ 1 s, current frame excluded), 50)` | 250 ms ("max 240 BPM") | `src/fl/audio/detector/beat.cpp.hpp:44-51, 91-124`; `beat.h:57-63` |
| **FastLED** `MultiBandBeat` | mean of bins 0–1 / 6–7 / 14–15 | none | relative rise vs previous frame > 0.15 / 0.12 / 0.08 | 10 frames (≈ 230 ms) | `multiband_beat_detector.h:15-27`, `.cpp.hpp:147-176` |
| **FastLED** legacy `Reactive::detectBeat` | PCM volume | attack/decay tracked previous volume | `volume > previous + 0.04 and > 0.02` | 100 ms | `audio_reactive.cpp.hpp:367-400` |
| **aubio** (used by LedFx `onset()`) | chosen ODF (hfc/specflux/…) | adaptive whitening + log compression for specflux; `silence` gate −70/−90 dB | median + mean × threshold over 7 frames | `minioi` 12–50 ms | `src/onset/peakpicker.c:103-123`, `onset.c:79-93` |
| **Cheap sound-activated light** (hardware) | microphone → band-pass (bass) → envelope follower | AGC / knob | comparator with hysteresis against a slow average | RC time constant ≈ 100 ms | — |

Observations:

1. **Every lighting product triggers on energy in a band (usually bass) relative to its own recent average, never on all-bin spectral change.** LedFx below 100 Hz; FastLED below ~650 Hz; WLED one bin; MA broadband energy but with a very fast post-peak EMA so only the *rise* counts. The academic onset detectors (aubio, madmom) are used by LedFx only for the `onset()` sparkle path and for tempo, not for the main flash.
2. **Ratios, not z-scores.** 1.5× (LedFx), 1.6× (MA), 1.3× (FastLED), slider (WLED). Nobody normalises by a standard deviation; everybody divides by a short running mean (0.2–1 s) and adds an absolute floor (LedFx `beat_min_amplitude 0.5`, FastLED `50`, WLED `sampleAvg > 1`).
3. **Dead time 80–250 ms** in all of them. That alone caps the event rate at 4–12 per second and makes a 16th-note hat pattern invisible to the trigger — by design.
4. **AGC first** wherever a microphone is involved (WLED PI loop, LedFx `mel_gain`, the disco light's knob). MA (line-level, loudness-normalised source) skips it.
5. **One or two user knobs**: WLED bin + threshold; LedFx none for the beat (three constants); MA a mode name; the disco light a sensitivity pot.

## 2. Tempo, where it exists

| Project | Method | Notes | File:line |
|---|---|---|---|
| LedFx | aubio `tempo` object → `bpm_beat_now()`, `beat_oscillator()` = sawtooth phase 0..1 from last beat and `get_period_s()` | effects (strobe, bar, …) animate on the **oscillator**, i.e. a tempo-locked clock, not on onsets | `ledfx/effects/audio.py:1170-1171, 1257-1265, 1362-1397` |
| Music Assistant | **offline**: Beat This! (neural) + pure-numpy DBN post-processor over the whole track; beats and downbeats scheduled to the player clock seconds ahead | "offline NN takes ~5-10 s"; the live onset is only a small boost | `providers/smart_fades/feature_extractor.py:1`, `dbn_postprocessor.py:1-13`, `providers/sendspin/player.py:2715-2750` |
| FastLED `Beat` | EMA (α 0.2) of the last inter-beat interval; phase = (t − last beat)/interval | one missed beat distorts BPM; no octave handling | `beat.cpp.hpp:138-175` |
| FastLED `TempoAnalyzer` | pairwise onset intervals → up to 5 BPM hypotheses (merge within 3 BPM, decay ×0.95/frame), winner through a 21-sample **median** ("rejects half/double-tempo outliers"); confidence decays with τ = 2 s in silence while BPM is held ("musical tempo has natural persistence") | 60–180 BPM, equal weight for 1×/2×/3× intervals | `tempo_analyzer.cpp.hpp:16-17, 26-32, 172-256, 266-335` |
| FastLED `MusicalBeat` | validates an onset only if its interval is within ±25 % of 60/BPM; confidence = 1 − 2·CV of the last 8 IBIs; `minBeatConfidence 0.5` | off by default; frame-counted; cannot follow a > 25 % tempo jump | `musical_beat_detector.cpp.hpp:36-75, 122-205` |
| WLED | none | — | — |

Observation: the two products with the *tightest* looking beats (LedFx strobe, MA) do not flash on detected onsets at all — they flash on a **clock** (aubio's tempo phase; an offline beat grid). Detected onsets only set or correct the clock.

## 3. How the light is shaped (the part we underrated)

| Project | Shape on a beat | Between beats | Contrast mechanism | File:line |
|---|---|---|---|---|
| LedFx `strobe` | brightness = `((−phase mod 1/f) × f)^strobe_decay × (1 − phase)^beat_decay`, then **squared** at output | falls to ~0 before the next beat | sawtooth from the tempo oscillator, squared | `ledfx/effects/strobe.py:49-65` |
| LedFx `power` | sparks overlay set to full on `onset()`, `*= decay_rate` per audio frame; bass bar from `lows_power` through ExpFilter | overlay decays to 0 | overlay on a dark background | `ledfx/effects/power.py:44-50` |
| LedFx `real_strobe` | queue of onsets, one strobe per render, `*= strobe_decay_rate` | 0 | full-white strike on black | `ledfx/effects/real_strobe.py:56-124` |
| Music Assistant Hue | per channel `floor + (max − floor) × min(1, transient × scale)` with transient = fast filter − **5 s baseline**; beat pulse = triangle ±8 % of the beat interval (≈ ±40 ms) that **multiplies** brightness by `pulse_peak` (1.8; downbeats 2.2 in "flashing"); onset boost +0.3 × strength, linear decay 250 ms | sits at the mode's **floor**: smooth 0.60–0.85, flashing 0.45–0.80, energetic 0.30–1.00, ambient 0.80 flat | low floor + multiplicative pulse; sustained bass gives no lift because the baseline catches up | `providers/hue_entertainment/analyzer.py:93-215, 234-238, 693-706, 736-762` |
| WLED Puddlepeak / Ripplepeak | strike (puddle size ∝ `volumeSmth`, ripple state 255) then `fade_out(fade rate)` every frame | fades toward background | strike on fading background | `wled00/FX.cpp:6734-6760, 7199-7215` |
| FastLED README idiom | `fill_solid(White)` on beat, `fadeToBlackBy(20)` every frame (≈ 8 %/frame) | fades to black | white strike on black | `src/fl/audio/README.md:121-153, 261-276` |
| Cheap disco light | relay / LED full on for the RC time, then off | **off** | 100 % duty contrast | — |

Observation: in every one of them the beat is a **strike from a low or dark base** (strobe squared, MA floor 0.45 × 1.8, WLED/FastLED fade-to-black), never a small additive lift on a bright base. MA's floor/max pairs are, in effect, the "pump" of a sidechain compressor: the music's sustained content is pushed down so the hit has somewhere to go.

## 4. Why LampaStream looks worse than a €15 light

1. Wrong trigger class: all-bin onset detection (recall-optimised) instead of bass-energy jump with ratio + dead time (precision-optimised).
2. No AGC / level reference in the trigger path; thresholds live on absolute flux scales.
3. No contrast model: lift is additive and small, base is the full effect brightness, release overlaps the next event.
4. Too many knobs, and the ones that matter (floor, dead time, ratio, sensitivity) do not exist.
5. Tempo is absent, so there is no clock to flash on and no way to reject off-grid transients.

Everything built in EVENT-01 … PREVIEW-01 (lossless timestamped events, time-based envelopes, scheduled sends, output capabilities, audible-clock preview) is still the right plumbing; it needs a different *producer* in front and a different *shape* behind.

## 5. Design that follows from the code (input to the replacement BEAT-01)

1. **Bass beat trigger (primary).** Energy of a 40–150 Hz band per 10 ms hop (from the existing long-window STFT), log-compressed, run through an AGC reference (slow peak follower, WLED-style setpoint, so line-level and quiet sources behave alike). Trigger when `band ≥ ratio × mean(band, 0.3 s)` AND `band ≥ floor` AND rising; ratio default 1.5 (LedFx/MA/FastLED cluster 1.3–1.6), post-peak fast EMA as in MA so sustained bass does not retrigger; dead time 100 ms, extended to 45 % of the beat period once tempo is locked. One user knob: **sensitivity**, scaling the ratio (and the floor). Broadband-energy fallback (MA's rule) when the bass band carries no beats for > 4 s.
2. **Secondary streams, low weight by default:** the existing mid/treble onset events (hats, snares) as "texture" with their own, higher ratio and 60 ms dead time; the all-bin spectral-flux stream stays available but off by default.
3. **Tempo from inter-beat intervals** (FastLED `TempoAnalyzer` approach, MIT, portable): hypothesis clustering of pairwise intervals, median against octave flips, confidence from hypothesis support + stability, confidence decays in silence while BPM is held. Plus a phase/clock (LedFx oscillator): next beat predicted from the last confirmed beat and the period, used to (a) validate candidates (±25 % IBI window), (b) extend the dead time, (c) drive a tempo-locked pulse when locked, (d) show BPM.
4. **Contrast model ("pump") instead of additive lift.** Per channel: base = effect colour × floor; on a beat the channel goes to max for one output frame and releases exponentially; floor/max/pulse factor are the Style's numbers (MA: smooth 0.60/0.85 ×1.0, flashing 0.45/0.80 ×1.8, energetic 0.30/1.00 ×1.2). Sustained content never lifts, because the beat gate — not the energy — opens the pulse. The accent layer, envelopes and quantisation guard stay; only the arithmetic changes from `lift toward full` to `floor + pulse`.
5. **Knobs for the user:** Sensitivity (trigger) and Intensity/Style (floor, max, pulse) — two. Everything else stays in Advanced with measured defaults.
6. **Measurement:** synthetic drum loops with ground truth (kick/snare/hat grids, pad texture, tempo change), events/s per stream, kick recall, false triggers on texture, BPM error, lock time, and the *visual* metric that matters: per-channel brightness between kicks must drop to ≤ floor + 10 % before the next kick (distinct flashes), on 25 Hz 8-bit and 60 Hz 16-bit rooms.

## 6. Sources (code)

- LedFx: `ledfx/effects/audio.py` (1134–1139 bands; 1207–1224, 1276–1300 beat; 1170–1171, 1257–1265, 1362–1397 tempo/oscillator), `ledfx/effects/melbank.py` (325–348 AGC), `ledfx/effects/strobe.py` (49–65), `power.py` (44–50), `real_strobe.py` (56–124).
- Music Assistant: `music_assistant/providers/hue_entertainment/analyzer.py` (93–215 modes and brightness model, 234–238 peak boost, 693–706 transient multiplier, 736–762 pulse), `bridge.py` (64–70 rates), `providers/sendspin/player.py` (2715–2750 beat schedule), `providers/smart_fades/feature_extractor.py`, `dbn_postprocessor.py`; aiosendspin `server/roles/visualizer/features.py` (515–546).
- WLED: `usermods/audioreactive/audio_reactive.cpp` (97–125, 194–203 AGC, 728–753 peak latch), `wled00/FX.cpp` (6734–6760, 7199–7215).
- FastLED (MIT): `src/fl/audio/detector/beat.cpp.hpp`, `beat.h`, `multiband_beat_detector.*`, `musical_beat_detector.*`, `tempo_analyzer.*`, `auto_gain.*`, `audio_reactive.cpp.hpp` (367–400, 648–721), `README.md` (121–153, 261–276), tests under `tests/fl/audio/detector/`.
- aubio: `src/onset/peakpicker.c` (103–123), `src/onset/onset.c` (79–93, 285–290).
