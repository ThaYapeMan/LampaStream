# Measurement protocol

Comparison anchor: baseline commit
**3998c440f464d0cf02743633fba98e8dd990743b**, recorded **2026-10-24**.
This specifies evidence for later phases; it adds no tracing, scheduler, DSP or
measurement implementation. [baseline.md](baseline.md) records the reference
setup and checks; [code-map.md](code-map.md) maps the current code contracts.
Physical results, output timing percentiles, normal-route event loss/duplication
and perceptual quality remain **not measured**.

## Run identity and comparison rules

For each later run retain the tested full revision and the baseline commit
3998c440f464d0cf02743633fba98e8dd990743b, UTC time, host/OS, Python/Node and native
library/dependency versions, producer gitlink, fixture IDs/hashes, decoder/sample
format, configuration export with secrets removed, source route, timing provenance,
head start/trim, output rate, selected Effects/EnergyProfile/Analyser, lamp/player,
network arrangement, camera mode and capture settings. Record warmup, duration,
repeat count, failures, drops and exclusions. Compare identical input/configuration
and separate live no-lookahead, measured-lookahead and any later whole-track mode.
Do not pool different players, lamps, source clocks or routes into one latency.

Keep raw traces and original captures alongside derived results locally. Report
sample count, p50/p95/p99, minimum/maximum, uncertainty and outlier counts, with a
stated quantile convention. Repeated runs must include ordinary playback and
pause/resume, seek/invalidation, source loss/recovery and changing delay. Report
startup/warmup separately from steady playback. Use paired runs against the full
baseline commit above; mark changed conditions explicitly instead of calling an
uncontrolled difference an improvement.

## Software evidence already available

Unqualified source references here are under `src/lampastream/`, at the full
baseline commit stated above. Existing variables are not necessarily persisted
traces. There is **no complete per-event trace across the pipeline today**.

| Evidence | Exists today | Limit |
|---|---|---|
| Canonical event/reporting sample position | Epoch and sample start/end in ProcessorUpdate and PublicationRecord (`spectrum_engine.py:101`, `spectrum_engine.py:127`) | An onset flag is attached to its reported hop; Dixon's local-maximum candidate is three hops earlier. The reporting position is not an independently verified event label. |
| Receipt and intended play clocks | `received_monotonic`, `play_monotonic`, `timing_generation` in PCM/features (`canonicalizer.py:61`, `types.py:201`); arrival/play spans transferred at publication (`sync_engine.py:1248`) | Receipt is source-read provenance, not detection/publication time. Play clock is optional and route-specific. Wall-clock capture timestamps must not be subtracted directly from monotonic clocks. |
| Publication time | Delivery `sequence` and exact audio interval, atomically committed (`sync_engine.py:1248`) | **No monotonic publication timestamp field** in PublicationRecord. Sequence alone cannot yield delivery latency. |
| Render time | Normal-route local `t=time.monotonic()` before render (`sync_engine.py:3214`); ready time after render is retained in timing provenance (`sync_engine.py:3233`). Timestamped route records `ready` (`sync_engine.py:3188`) | Not a durable event-keyed trace. The timestamp passed to early render can be future intended play time, rather than render invocation time. |
| Scheduled scene time | SceneSchedule queue key is `max(ready, play+trim)` (`airplay_early.py:347`) | Bounded transient queue; due scenes may be coalesced. Not a persistent schedule audit. |
| Send time | Monotonic time immediately before `output.send`, retained as shown-scene time and passed to optional diagnostics (`sync_engine.py:3200`, `sync_engine.py:3281`) | API invocation only. Driver can decline a frame while not streaming; dependency DTLS thread/network/Hue processing is later. No per-event wire-send or light-response timestamp. |
| Diagnostic processing samples | Receipt → scene-ready → send supplied to TimingDiagnostics (`airplay_timing.py`, `lms_timing.py:275`) | Bounded software estimates; do not equal audible-to-visible offset or guarantee event delivery. |
| Decision/availability time and candidate strength | **Missing as event records** | Dixon returns the current raw flux when deciding about a buffered candidate (`sync_engine.py:444`); it does not expose candidate-frame strength or that candidate's event/decision timestamp as a coherent event record. |

Offline acceptance (`scripts/run_acceptance.py:425`) captures delivery-order
records and sample-derived audio time; it is not a wall-clock render/output trace.
Sample seconds are `sample_position / 48000` within an epoch. Do not infer source
duration from publication count, padded FFT input or last reported hop. Check
sequence gaps and `pub_dropped_count` before draining the bounded queue.

## Seven points in the time chain

The logging locations below are measurement boundaries for later work, not
claims that these logs already exist. Correlate by fixture/event ID, epoch,
interval, publication sequence, scene identity and timing generation. Keep event
sample time, availability time and intended presentation time as distinct values.

| Point | Definition and where it would be logged |
|---|---|
| 1. Event sample position | Known click/annotated event sample in source and canonical coordinates. Save with fixture truth; log the detector candidate's own sample index at `BeatDetector.feed` / picker boundary (`sync_engine.py:911`, `sync_engine.py:444`). Preserve resampling/epoch mapping. |
| 2. Analysis window reference | Window start, centre/end convention, FFT length/hop and actual PCM extent used for that decision. Log at shared STFT/processor dispatch (`sync_engine.py:1385`); explicitly distinguish the 2,048-sample window from the 480-sample reporting interval and Dixon's buffered candidate. CAVA owns a different FFT/window path. |
| 3. Detection availability | Monotonic instant the decision is available, then publication commit time. Log separately at picker/processor return and `_publish` (`sync_engine.py:444`, `sync_engine.py:1248`), with candidate-frame strength rather than only current flux. This distinguishes window/lookahead delay, compute delay and delivery delay. |
| 4. Scheduled scene time | Requested audible target, trim, ready time, final target and scene/event identity. Log at SceneSchedule.add (`airplay_early.py:347`), or normal-route render/enqueue with target delay/depth (`sync_engine.py:3233`). Include coalescing/overflow/cancellation outcomes. |
| 5. Send time | Log API call/accept-or-reject at `HueDriver.send` (`hue_output.py:399`); if measuring transport, also capture actual dependency DTLS enqueue/transmit boundaries. Keep these clocks separate and retain burst order when normal delay shrinks. |
| 6. Audible sound | Acoustic click onset at the listening/measurement position, recorded with the lamp capture or independently synchronized audio sensor. Label in the physical recording. A player's intended play timestamp or LMS position response is not this measurement. |
| 7. Measured light | First reproducible lamp intensity change at the selected region/threshold, with frame index or sensor clock and rise profile. Label in original video or photodiode capture. Hue send time is not visible-light time. |

For each matched truth event report detector misses, extra decisions, repeated
output reactions and coalesced/not-sent scenes separately. Define a fixed matching
window and one-to-one matching rule before comparing revisions; publish its value
with the results. Count unmatched truth events as misses and extra emitted
reactions as extras/duplicates, rather than dropping them from latency statistics.
The normal polling route can both miss and reuse onset flags; the timestamped
route can coalesce due scenes. Neither observation is a measured rate yet.

## Physical audio-to-light measurement

Use the owner's iPhone **4K120 (120 fps)** or **240 fps slow-motion**, verifying
the actual recorded frame cadence and whether that mode includes usable audio.
Nominal frame periods are **8.33 ms** and **4.17 ms** respectively. Record camera
and microphone positions, speaker/lamp distances and any calibration; repeat with
unchanged placement. Do not claim sub-frame precision from ordinary frame labels.

Play a click track with known sample positions and well-spaced clicks, or use a
known light pattern to characterize light response independently. Capture the
lamp region and the audible reference in one synchronized recording where
possible. If slow-motion audio is unavailable or retimed, use a separately
synchronized audio recording or visible timing reference and document the clock
mapping; silent slow-motion alone cannot establish audio-to-light offset.
A known pattern by itself measures light response, not music event detection.

Lock exposure, focus and white balance. **Lock exposure low enough that the lamp
is not clipped**: saturated white frames hide the rise and cannot measure
brightness timing reliably. Keep the lamp region and background fixed, subtract
background, retain raw intensity curves, and state the onset threshold/interpolation
rule before comparing captures. Check rolling-shutter position, exposure duration,
audio/video alignment, variable/dropped frames and camera processing as sources of
uncertainty. Record rather than silently compensate unknown camera offsets.

Define signed physical offset as **light onset minus audible onset**: positive
means late light. Report central offset separately from jitter (spread around
the central offset) and outliers (counts, magnitudes, and reasons under a declared
rule). Include all runs and lost/extra reactions; retain long tails in p95/p99.
Report software target-to-send error separately from physical sound-to-light
error, and never subtract uncalibrated independent clock domains. Stratify by
lamp model, player and route; do not generalize one Hue Iris capture to all lamps.

Perceptual evaluation is a separate blinded, paired local comparison using the
same fragments and settings. Record preferences and concrete observations about
rhythm, calmness, colour and transitions; neither passing tests nor lower latency
alone establishes perceptual improvement.

## Dataset policy

Start with **about 20 fragments**: three from each of **techno, house, deep house,
hard dance and disco** in the owner's library (15 musical fragments), plus
**ambient, speech, silence, anti-phase stereo and clicks** (five edge/control
fragments). Dataset labels need not equal the product's normalized genre taxonomy.
Retain deterministic generation specifications for synthetic controls.

Use three explicitly identified sets:

- **Development:** tuning and exploratory listening; one musical fragment per genre.
- **Regression:** repeatable correctness/timing checks; a different fragment per
  genre plus the five edge/control fragments.
- **Held-out:** a third musical fragment per genre, reserved from tuning and opened
  only for evaluation at an agreed comparison point.

Split by track/recording, not adjacent excerpts from the same recording. Keep the
split fixed, version local manifests, record hashes, clip boundaries, decoding
and level treatment, and log every move between sets. Freeze matching/threshold
rules using development evidence before held-out scoring. When held-out material
has informed tuning, mark it consumed and choose replacement held-out recordings.
Report per-fragment results as well as aggregates; silence and anti-phase cases
are correctness controls, not genre-quality scores.

**Music stays local and is never committed.** Store private material in a
`private-fixtures` directory **outside the checkout**, with captures, private
identifiers and manifests kept local as well. Do not add music via Git LFS,
archives, screenshots, CI artifacts or embedded base64. Commit only redistributable
synthetic-generation specifications or non-identifying measurement schemas when
later tasks explicitly request them. This task creates no dataset or harness.
