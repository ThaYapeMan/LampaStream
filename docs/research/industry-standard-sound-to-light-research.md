# Industry practice for beat-reactive lighting — research

Date: 2026-10-27. Sources: manuals, developer documentation, protocol specifications, patents and open-source code; every row cites its source. Items that could not be verified from a primary source are marked [unverified]. Companion to `competitor-beat-trigger-code-analysis.md` (open-source code) and `no-onset-missed-event-pipeline-research.md`.

## 0. Short answer

1. **Professional lighting does not derive "the beat" from live audio when it can avoid it.** Tempo comes from a clock or a pre-analysed grid: tap tempo, MIDI clock (24 PPQN), Ableton Link (tempo + bar phase), OS2L (VirtualDJ `beat` messages with BPM, position and strength), Pro DJ Link (per-beat packets with beat-within-bar), or the DJ software's analysed beat grid and phrases (rekordbox: "if tracks are not phrase-analyzed, you cannot perform lighting in sync"; SoundSwitch scripts and Autoloops follow the beatgrid). Live audio is the fallback and the modulation source (level → intensity), not the primary beat source. Consumer flagships went the same way: Hue + Spotify uses track metadata "light scripts" for "zero lag"; Music Assistant's Hue plugin uses pre-analysed beats and falls back to onsets.
2. **When live audio does trigger, the definition is uniform across the industry:** a fixed filter bank of ~7 bands with the lowest at 50–63 Hz (Avolites Titan 50/140/380/875/2400/6200/14000 Hz; ChamSys MagicQ 63/160/400/1k/2.5k/6.2k/16k; ETC 15–100/100–360/360–1296/1296–4665/4665–22050 Hz at 24 dB/oct), a per-band threshold that is manual or auto-tracked (Titan "Auto" re-tracks when no triggers occur), a trigger on the band *peak* crossing the threshold, a rate divisor (every n-th beat), and AGC in front (Titan auto gain, QuickQ automatic gain, ETC 100 ms envelope follower, WLED AGC presets). DMX fixtures' own "sound active" mode is the same with a microphone and a 0–100 sensitivity: Chauvet Sentinel Wash Q120 manual — "The product will only respond to low frequencies of music (bass and drums)"; the Fourstar patent US10492277 for cheap sound-active controllers — "detects primarily only the bass of music", thresholds adapt to the average level.
3. **Light shaping on a beat is "bump/flash then fall"**: grandMA3 Sound Fade (fall-off speed), MagicQ response modes Normal / Decayed / Pulse / Pulse-decay with a decay-rate or pulse-duration parameter, Resolume Fall, MADRIX Frequency Flash (default 96 Hz centre, 22 % bandwidth, 80 % threshold, fade-in 120 / fade-out 3000 in BPM units ≈ instant attack, visible release), Onyx beat display modes Phase (fading flash) / Flash / Alternate (every other beat) / Pulse. Nobody exposes attack time.
4. **Few user controls**: gain or auto-gain, per-band threshold/sensitivity, band selection (Bass/Mid/High/Energy), rate divisor, fall time, a beat-latency offset in ms (Onyx ± Beat Latency, VirtualDJ `os2lBeatOffset`, Music Assistant "Light latency" default 20 ms), and an intensity preset (Hue Sync: Subtle / Moderate / High / Intense).

## 1. Professional consoles and media servers

| Product | Beat source | Live trigger | Shaping | Controls | Source |
|---|---|---|---|---|---|
| grandMA3 | Live-audio BPM detector ("BPM speed master locks on to a beat"), cue trigger type BPM | Cue trigger type Sound with 22 frequency areas (All, Bass, Mid, High, Band1–7 and inverses); a dot marks a possible trigger (peak) per band | Sound Fade master = fall-off speed; phasers driven by sound channels | Sound In gain, Sound Fade, BPM master; input ≥ 50 mV | help.malighting.com grandMA3 2.3 Sound Viewer; cue sheet trigger types |
| ChamSys MagicQ | Audio Input BPM; speed-master sources Audio Beat / Audio BPM / DJ Beat (OS2L) | 7 bands 63 Hz–16 kHz + Energy; global min/max audio level window | Audio bumps GO/FX on each detected peak with rate divisor; Audio beat step (4/8/16-beat loops); Audio sets BPM; fader modes Normal/Decayed/Pulse/Pulse-decay/Switch/Slow with decay rate or pulse duration | band, level, two parameters, divisor; QuickQ: auto gain, band select (63 Hz for bass) | secure.chamsys.co.uk MagicQ manual "Audio"; QuickQ 9 audio |
| Avolites Titan | BPM masters from tap/MIDI; audio is a trigger stimulus | 7 bands 50 Hz–14 kHz; per band trigger level, enable, Auto (self-adjusting threshold); global gain + auto gain | Actions: Set Level, Fire at Level, Re-fire, Flash, Swop, Preload, Latch | gain/auto gain, per-band level/auto, action | manual.avolites.com Titan 18 "MIDI, DMX or audio triggering" |
| Obsidian Onyx | Beat Provider: Ableton Link, MIDI clock, tap, or audio analysis; BPM range, lock, ± Beat Latency, Beat Fade Time when BPM is lost | audio: input gate + gain only | display modes Phase (fading flash), Flash, Alternate, Pulse, Quantum | gate, gain, range, lock, latency, fade | support.obsidiancontrol.com Beat Provider |
| ETC (ColorSource AV, Sound2Light) | level-driven | 5 bands + rest state, 24 dB/oct, 15 Hz HPF; AGC envelope follower 100 ms; 5 s activation time constant | band → fader | per-band faders | support.etcconnect.com Sound2Light frequency bands |
| QLC+ | OS2L beat from VirtualDJ; tap | Audio Triggers: volume + 5–32 spectrum bars, enable/disable thresholds (hysteresis), divisor ≤ 64 | channel ∝ band, function start/stop, tap, cue next | bars, thresholds, divisor | docs.qlcplus.org Audio Triggers, OS2L plugin |
| MADRIX | S2L frequency/volume; no BPM | Frequency Flash: 96 Hz, 22 %, threshold 80 % | flash with fade in 120 / fade out 3000 (BPM units) | frequency, bandwidth, threshold, fades | help.madrix.com M5 S2L Frequency Flash |
| Resolume | global BPM (tap/Link/MIDI clock) | FFT L/M/H or in/out points; Gain; Fall | parameter or speed | gain, fall, band | resolume.com parameter animation |
| TouchDesigner audioAnalysis | none | Low/Mid/High threshold, smooth, gain; kick/snare/rhythm thresholds | user network; Trigger CHOP ADSR | as listed | derivative.ca Palette:audioAnalysis |
| Daslight 5 | tap, MIDI clock, Ableton Link; "react to the music pulse" | sensitivity auto/manual | scene steps per beat | tap/Link/MIDI, pulse | bekafun Daslight 5; Elation forum [detail unverified] |
| Pangolin BEYOND | tap/manual BPM, resync | — | beat-based effects | tap, BPM | wiki.pangolin.com beats |
| Lightjams | audio engine exposes /audio/beat, /beatPh (sawtooth), /bpm, /bar, /break, /drop, /energy | internals not public | — | — | Lightjams group [internals unverified] |

## 2. DJ ecosystem (grid-driven)

| Product | Beat source | Driven | Source |
|---|---|---|---|
| rekordbox Lighting | phrase analysis + beat grid; Mood HIGH/MID/LOW from tempo, rhythm, kick drum, density | scenes, banks, macros per phrase | rekordbox FAQ lighting-6/7; Pioneer patent US10512139 (offline beat/tempo analysis, lighting snapped to grid) |
| Serato + SoundSwitch | autoscript and Autoloops from the beatgrid; v2.9 adds real-time Auto BPM from any audio as fallback | scripted tracks, Autoloops, static looks | serato.com blog; SoundSwitch 2.9 release |
| VirtualDJ → OS2L | one JSON per beat: `{evt:'beat', change:false, pos:21, bpm:121.96, strength:0.9}`; `os2lBeatOffset` ms; DNS-SD discovery | Sunlite/Daslight phase follows master deck; QLC+ channel; MagicQ DJ Beat | VDJ forum; QLC+ OS2L; github lordvonadel/os2l [field semantics unverified] |
| Pioneer Pro DJ Link | per-beat UDP packets: BPM, pitch, beat within bar, master flag | any consumer | github Deep-Symmetry/beat-link wiki |
| Ableton Link | shared tempo + phase in [0, quantum) | any peer | Link.hpp; rekordbox Link FAQ |
| MIDI beat clock | 0xF8 at 24 PPQN, start/continue/stop, song position | chase speed | Wikipedia MIDI beat clock |

## 3. DMX fixtures' built-in sound-active

| Fixture | Mechanism | Sensitivity | Triggers on | Source |
|---|---|---|---|---|
| Chauvet Sentinel Wash Q120 (2025) | internal mic; sound-active programs; 5 s on/off delay for sound-active pan/tilt and colour | menu 001–100; DMX speed channel | "only … low frequencies of music (bass and drums)" | Chauvet UM Rev1 2025 |
| ADJ LED Fury / Mushroom | internal mic; DMX ch.2 0–255 = sound sensitivity | 00–99 | "beat of the music" | adj.com manual |
| Martin RUSH MH 10 Beam FX | mic; scene changes "in sync with a music beat" | SOUND SENSE 0–100 | beat | Harman help |
| Showtec Phantom 75 Beam | mic; sound-controlled programs 1–8 | — | beat | Showtec manual |
| Fourstar patent US10492277 | mic → preamp → MCU; bass-only waveform timing; thresholds adapt to average level; two preamp stages for 65–110 dB SPL | adaptive | bass beats per window | Google Patents |

## 4. Consumer products

| Product | Beat source | Trigger | Shaping | Controls | Source |
|---|---|---|---|---|---|
| Philips Hue + Spotify | Spotify track metadata light scripts (mood, genre, tempo, segments, loudness, pitch); "zero lag" | none | script | brightness, intensity, palette | Signify PR 2021; Signify patent US12446126 |
| Hue Sync desktop (music) | live computer audio; internals unpublished | unpublished | unpublished | Subtle/Moderate/High/Intense, speed, brightness, palettes | Signify PR 2018 [algorithm unverified] |
| Music Assistant Hue plugin | pre-analysed beats (Beat This! + DBN), fallback peak/onset | energy > 1.6 × EMA, 80 ms | Smooth/Ambient/Flashing/Energetic; stronger on downbeats | brightness, mode, Light latency 0–3000 ms (default 20) | music-assistant.io plugin page; code (see companion analysis) |
| Nanoleaf Rhythm | mic or aux; "detect the beat"; reaction tied to volume and duration | unpublished | 8 scenes (Pulse Pop Beats dims/brightens with the beat, …) | brightness, source | MacRumors review; Nanoleaf API rhythmMode [DSP not found] |
| Govee | mic (Music Sync Box) | unpublished | 22 music modes | sensitivity | govee.com [mode semantics unverified] |
| WLED audioreactive | no beat tracking in core docs; 16-band GEQ + volume | squelch 1–20/≤64, gain 1–255 ≈ −20…+16 dB, AGC Off/Normal/Vivid/Lazy | per effect | squelch, gain, AGC | kno.wled.ge audio reactive |
| FastLED MultiBandBeat | per-band energy rise with cooldown | bass 20–80 Hz (as documented; in code 90–149 Hz), mid 320–640, treble 5120–16000; thresholds 0.15/0.12/0.08 | flags | thresholds | fastled.io docs; code analysis |

## 5. Numbers

| Quantity | Values |
|---|---|
| Lowest trigger band | 50 Hz (Titan), 63 Hz (MagicQ), 15–100 Hz (ETC), 96 Hz centre (MADRIX), 20–80 Hz (FastLED doc) |
| AGC time constants | ETC 100 ms envelope follower; WLED fast 0.15 s / slow 2–15 s; Fourstar adaptive to average level |
| Dead time / rate | MagicQ rate divisor; QLC+ divisor ≤ 64; Onyx Alternate; FastLED cooldown 250 ms; MA 80 ms; LedFx/WLED 100 ms |
| Fall/decay | MADRIX fade-out 3000 (BPM units); MagicQ decay rate / pulse duration; grandMA3 Sound Fade; Resolume Fall |
| Latency offsets | Onyx ± Beat Latency; VDJ `os2lBeatOffset`; MA 20 ms default render-ahead; NUS "Dazzler" target < 50 ms |
| Perception | asynchrony detectable from ~20 ms in the lab; tolerance can exceed 200 ms; audio-lead (light late) is detected sooner than light-early (Frontiers 2015) |
| Tempo distribution | MIDI clock 24 PPQN; Link tempo + phase; OS2L one message per beat; Pro DJ Link beat-within-bar |

Academic note: "Automatic Stage Lighting Control: Is it a Rule-Driven Process or Generative Task?" (arXiv 2506.01482, RPMC-L dataset of 699 live-show clips) finds rule-based baselines poor on rhythm (2.65/7 vs 4.48 ground truth) and lists beat tracking as future work; no paper giving per-beat flash-duration or band→intensity rules was found.

## 6. What counts as industry standard

- **Primary model: the beat is a clock.** Consoles consume a BPM/speed master (tap, MIDI, Link, OS2L, Pro DJ Link, or their own audio BPM lock); DJ lighting consumes analysed grids; the flagship consumer product consumes track metadata. Where live BPM detection exists it is wrapped as a clock with range, lock, latency offset and fade-out-when-lost (Onyx), not as per-onset flashing.
- **Secondary model: a live bass-band trigger with threshold, AGC, hold and divisor.** Uniform across consoles, fixtures and the cheap sound-active controllers.
- **Shaping: instant attack, user-set fall, a floor (the base look) under the bump, downbeat emphasis where bar phase is known.**
- **Controls: intensity preset, sensitivity 0–100 with AGC on, band, divisor, fall, latency offset, palette.**

## 7. Recommendation for LampaStream (live PCM, Hue now, WLED/DMX later)

1. Two layers: a **tempo clock** (BPM + bar phase, lock/range/fade-out-when-lost, ± latency offset) and a **bass-band trigger** (50–100 Hz, AGC with ~100 ms envelope follower and a slow reference, adaptive threshold that re-tracks when idle, dead time ≈ 60 % of the beat period or 100 ms when unlocked, rate divisor). Fusion: the clock schedules the flash, the trigger confirms presence and corrects phase; when triggers vanish (breakdown) the beat effect fades over a Beat Fade Time instead of stopping; with no stable tempo, pure trigger mode. The clock is what allows rendering ahead on the timestamped route.
2. Shape like a console: instant attack, fall time as the main creative parameter, floor = the effect's base look, presets Phase / Flash / Alternate / Pulse, downbeat emphasis from bar phase.
3. Controls: Intensity preset (Subtle/Moderate/High/Intense → threshold, flash depth, fall), Sensitivity 0–100 (AGC on), Band (Bass/Mid/High/Energy), Divisor, Fall, Beat latency ± ms, Palette. FFT size, hop, attack and hysteresis widths stay internal.
4. External clocks later, exactly as consoles do: Ableton Link, MIDI clock, OS2L `beat`; when present they replace the internal tracker and the bass trigger only modulates. The same engine maps onto WLED's gain/squelch/AGC vocabulary and DMX "sound-active program" semantics.

## 8. Not verifiable this session
ETCLabs/Sound2Light source defaults; os2l.org spec text; Notch, MadMapper, Lightjams internals; DMXControl, Martin M-PC, Daslight 5 manual PDF; SoundSwitch "Sound Activated" mode; Hue Sync desktop algorithm; Nanoleaf Rhythm DSP; Govee mode semantics; official Hue Entertainment stream-rate limit.

## 9. Sources
grandMA3: https://help.malighting.com/grandMA3/2.3/HTML/sound_viewer.html , https://help.malighting.com/grandMA3/2.3/HTML/cue_sequence_sheet.html , https://help.malighting.com/grandMA3/2.3/HTML/fs_connect_audio_in.html · ChamSys: https://secure.chamsys.co.uk/docs/magicq/manual/audio.html , https://docs.chamsys.co.uk/quickq/9.0/audio/audio.html , https://info.chamsyslighting.com/article/715-using-dj-integration-to-set-bpm-to-speedmasters · Avolites: https://manual.avolites.com/docs/18.0/running-the-show/midi-dmx-or-audio-triggering · Onyx: https://support.obsidiancontrol.com/Content/Onyx_Manual/Programming/DyLOS/Input_Processors/Beat_Provider_Input_Processor.htm , https://forum.obsidiancontrol.com/t/audio-in-trigger/6980 · ETC: https://support.etcconnect.com/ETC/Consoles/ColorSource/ColorSource_20_and_40_AV/Sound2Light_Frequency_Bands · QLC+: https://docs.qlcplus.org/v4/virtual-console/audio-triggers , https://docs.qlcplus.org/v4/plugins/os2l · MADRIX: https://help.madrix.com/m5/html/madrix/hidd_effect_s2l_frequenzflash.html · Resolume: https://resolume.com/support/en/6/parameter-animation , https://resolume.com/forum/viewtopic.php?p=87503 · TouchDesigner: https://derivative.ca/UserGuide/Palette:audioAnalysis , https://docs.derivative.ca/Trigger_CHOP · Daslight: https://bekafun.com/en/news/n/430/New-Daslight-5 · BEYOND: https://wiki.pangolin.com/beyond:music_and_beats_overview · rekordbox: https://rekordbox.com/en/support/faq/lighting-7/ , https://rekordbox.com/en/support/faq/lighting-6/ , https://patents.google.com/patent/US10512139 · SoundSwitch: https://serato.com/latest/blog/20236/soundswitch-12-released-major-update , https://news.hummingbirdmedia.com/lighting-control-software-soundswitch-announces-version-29-with-auto-bpm-detection-and-enhanced-autoloop-features · OS2L: https://virtualdj.com/forums/261216/VirtualDJ_Technical_Support/Extended_OS2L_parameters_in_VirtualDJ.html , https://virtualdj.com/wiki/OS2L.html , https://github.com/lordvonadel/os2l · Pro DJ Link: https://github.com/Deep-Symmetry/beat-link/wiki · Link: https://hackage-origin.haskell.org/package/tidal-link-1.0.2/src/link/include/ableton/Link.hpp · MIDI clock: https://en.wikipedia.org/wiki/MIDI_beat_clock · Chauvet: https://es.chauvetdj.com/wp-content/uploads/2025/07/Sentinel_Wash_Q120_UM_Rev1.pdf · ADJ: https://www.adj.com/cdn/shop/files/led_fury.pdf · Martin: https://harman.helpjuice.com/en_US/rush-mh-10-beam-fx-sound-activation · Showtec: https://images.static-thomann.de/pics/atg/atgdata/document/manual/335541_phantom_75_beam_uk.pdf · Fourstar: https://patents.google.com/patent/US10492277 · Signify: https://www.assets.signify.com/is/content/Signify/Assets/hue/global/20210901-philips-hue-spotify-feel-the-music.pdf , https://www.signify.com/en-us/about/news/press-releases/2018/20180531-create-surround-sound-for-your-eyes-with-philips-hue-sync , https://patentsgazette.uspto.gov/week41/OG/html/1539-2/US12446126-20251014.html · Music Assistant: https://www.music-assistant.io/plugins/hue-entertainment/ · Nanoleaf: https://www.macrumors.com/review/nanoleaf-aurora-rhythm · Govee: https://us.govee.com/products/govee-music-sync-box · WLED: https://kno.wled.ge/advanced/audio-reactive/ , https://mm.kno.wled.ge/WLEDSR/Squelch-and-Gain · FastLED: https://fastled.io/docs/d8/d35/classfl_1_1audio_1_1detector_1_1_multi_band_beat.html · Perception: https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.00736/full · Stage lighting ML: https://arxiv.org/html/2506.01482v2 · Spotify analysis deprecation: https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
