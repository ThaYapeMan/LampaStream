# PCM, clocks, lifecycle and publications

## Source and canonical frames

Production stereo adapters return `SourceReadResult`: decoded data, temporarily
no data, clean EOS or invalidation. DecodedSourceFrame contains complete float32
mono/stereo frames at the source rate; the source performs integer decoding and
channel alignment. Published arrays are owned/read-only.

AudioCanonicalizer produces 48 kHz, two-channel float32 AnalysisPcmFrame objects,
nominally in [-1,1]. Mono is duplicated; rate conversion uses soxr. It maintains
stream epochs and canonical frame positions, not transport-byte positions or wall
clock timestamps. Invalidation discards uncertain carry. Clean EOS drains valid
resampler output. Source adapters must report continuity loss before post-gap PCM.

The manager opens and ultimately closes physical sources. The canonical worker
reads source events and owns canonical DSP lifecycle. A manager cannot close/reuse
that source until every owned worker terminates.

## SharedAnalysisFrame

Every canonical frame reaches shared STFT and all enabled processors exactly once,
independently of Spectrum readiness. SharedAnalysisFrame supplies PCM, magnitude
frames, epoch, canonical transport interval and `hop_sample_starts` for each STFT
output. These hop positions are chunk-independent. The transport interval is
**not** an instruction to overwrite a ProcessorUpdate's interval.

V2 consumes magnitudes. Beat consumes the same magnitudes with its own algorithm
state. CAVA consumes PCM and retains its own FFTs. Future PCM/magnitude consumers
can use the same frame; the current worker dispatches sequentially.

## Event time versus delivery order

A PublicationRecord binds sequence, epoch, sample_pos (interval start), sample_end,
AudioFeatures, effective engine ID, fresh processor IDs and optional carried
Spectrum interval. Sequence/latest/queue commit under one lock.

Sequence is monotonic delivery order. Audio intervals can arrive out of order:
CAVA [1920,2400) may be available before Beat [0,480). The later Beat record remains
[0,480); it is not discarded, shifted or unioned with a transport interval.
`latest()` is the freshest live snapshot by `(sample_end, sample_start)` within
an epoch. An exact interval tie prefers the later delivery, so same-interval Beat
can update the live snapshot. A new epoch clears the old snapshot before publishing.
The queue still includes every delivered record, even when a delayed record does
not replace the live snapshot. Sequence/latest/queue are updated under the same
lock, but latest's sequence can be less than the delivery counter. Live Effects
therefore do not replay older intervals merely because they arrived late.

Per dispatch, exact interval keys merge. Spectrum-bearing keys are delivered first,
then other first-seen keys in processor/update order. Equal keys merge regardless of
list position. A delayed result for a previously published interval creates a new
sequence; it does not rewrite earlier records. EOS follows the same policy.

Historical Spectrum bars may accompany a delayed contribution only when their
interval matches exactly, or ends at/before its start. The record explicitly reports
`carried_spectrum_interval`; fresh contributor IDs exclude historical Spectrum.
No future bars are substituted. If the bounded history cannot supply bars, the
record has empty bars but retains its real contribution and interval.

## Bounds and consumer responsibilities

- No pending map waits for slow/silent processors. Every valid returned update is
  handled in the current dispatch.
- Spectrum history retains at most 1000 entries. Eviction removes optional bars,
  not delayed processor results.
- The publication queue retains at most 1000 records. Overflow increments
  `pub_dropped_count`; 1006 undrained publications produce 6 evictions.
- `drain_publications()` returns queued records and resets drop counters. Inspect
  the count before draining; sequence gaps also reveal missed delivery. This is
  best-effort bounded history, not a durable event log.
- The obsolete `pub_late_dropped_count` API has been removed. Late delivery is
  valid, not a drop; only bounded-queue overflow has drop telemetry.
- Polling `latest()` may miss intermediate events. Offline acceptance captures the
  lists returned from public feed/EOS calls; consumers must not infer new delivery
  from feature-value equality or assume CSV timestamps are globally sorted.

## Lifecycle

| Event | Behavior |
|---|---|
| Normal PCM | Canonicalize, shared analysis, generic feed, publish |
| TemporarilyNoData | No inserted silence, no reset, terminal/latest remains |
| StreamInvalidated | Discard uncertain carry; reset processors/STFT; clear latest |
| New epoch | Reset old analysis/history; establish new clock; clear old latest |
| Clean EOS | Drain canonical source; flush all processors; publish valid intervals; reset DSP; preserve terminal latest |
| Stop succeeds | Worker joined; processors closed exactly once |
| Stop times out | Return incomplete; worker/source ownership retained; worker closes processors on exit |

CAVA zero-pads a final short native block only. Its publication ends at the valid
source boundary: 481 source frames give [0,480) and [480,481). Canonical source
duration is independent of padding, STFT warmup and publication count.

Retirement status is observational: a completed worker remains tracked until an
explicit stop/replacement joins or reaps it. Merely reading status does not erase
the timeout before the manager handles it.

Manager deactivation can be retried. An incomplete stop raises an explicit error,
retains the session/source, and exposes `analysis_stopping=true`. A new activation
first completes that teardown. Source close and release happen only after termination.
Do not repeatedly call pipeline.start on a retiring analyser.

Follower teardown is separately owned: stop the follower once, cancel and await its
task (including connection cleanup), then clear its references. Analysis retirement
retries do not repeat follower cleanup. Errors other than the expected task
cancellation propagate; they are not converted into successful cleanup.

## Independent track metadata channel

Track metadata does not enter PCM, analysis processors, or `AudioFeatures`.
`ActiveSession` owns a separate `TrackPositionSource` (`open`, asynchronous
`close`, nonblocking `read`, and `running`). `PlayerManager` selects the adapter;
WebSocket delivery and the track/progress UI consume the same immutable
`TrackPosition` regardless of player type. Session teardown awaits the metadata
reader before releasing it, including failed activation and retried teardown.

- **LMS:** a dedicated read-only `status - 1 tags:ad subscribe:10` connection
  receives changes and ten-second corrections. `a` requests artist, `d` duration,
  and title is a standard field ([CLI tags](https://lyrion.org/reference/cli/database/#songinfo),
  [subscriptions](https://lyrion.org/reference/cli/compoundqueries/#status)).
  The target comes from the existing follower's `target_mac`: pinned manual
  target or dynamically selected sync-group peer. With no manual follower,
  it queries LampaStream's own player. Unsynced auto mode returns no track. The
  adapter checks the local target each second without querying LMS again and
  discards old-target snapshots immediately. It sends no playback/group commands.
- **AirPlay:** the pinned Shairport build enables metadata and writes a separate
  `/run/lampastream/airplay.metadata` FIFO, owned by `lampastream` with mode `0600`.
  `core/minm` and `core/asar` supply title and artist. `ssnc/prgr` gives
  start/current/end RTP timestamps; differences use wrapping 32-bit coordinates
  with a signed pre-roll anchor when current precedes start
  and 44,100 frames/second. Configured ten-second `phbt` updates correct position;
  pause/resume/end events control interpolation. When early-tap RTP timing is
  available, track zero is derived from that same native playback clock; metadata
  receipt time is used only in pipe fallback. See the upstream
  [metadata protocol](https://github.com/mikebrady/shairport-sync-metadata-reader).

Snapshots retain a monotonic position anchor. WebSocket delivery rebases the
position when sending a changed status, so browsers do not need a synchronized
server clock. The UI interpolates locally only while playing and connected,
clamps at known duration, and shows unknown values as `—`. This is track progress,
not a measurement of lighting/audio latency. Metadata availability depends on
what the sender provides; live streams may have no duration. The manager retains
one receiver reader and metadata cache in standby, so coupling switches preserve
already-announced track anchors. If the application itself starts after the only
progress announcement, a subsequent sender update is still needed; track origins
are never invented from wall time.

Local tests cover CLI subscriptions, dynamic targets, real FIFO reads, RTP wrap,
pause/seek/end, bounded parsing, teardown, and generic UI rendering. Live LMS,
iOS sender behavior, and the rebuilt target Shairport service still require LXC
validation.

The pinned upstream yeney-core producer is `9fba26f` (ALAC `5d8c5db`).
Its optional 64-byte YNPT tail exports `content_frame` at offset 52 and
`content_flags` at offset 60 (bit 0: known). No local producer patch is applied.
The segment is `/dev/shm/yeney-<lowercase-mac>`; the SHM v1 layout, ABI version,
YNPT tail and `measurement_basis=lms-content-v1` contract are unchanged.

## Live beat accents and the relative onset gate (schema 5)

Coupling `beat_accent_mode` is live: Off supplies no accent events; Onset admits
confirmed detector candidates through RelativeOnsetGate; Tracker consumes the
existing fused stream. Selection happens before scheduler intake. Detector
candidate generation, peak picking, canonical sample timing, audible clocks,
tempo estimation and the Effects → Scenes boundary are unchanged.

The Onset gate uses the detector's raw onset-strength envelope at **every
analysis frame**, including zero and non-candidate frames. Over [t−W,t], where
W=`onset_reference_window_s` (3 s), background is the median and spread is the
unscaled median absolute deviation (MAD). An accent requires raw candidate
strength ≥ background + k × spread, plus the existing detector absolute minimum.
A candidate equal to a perfectly flat background (MAD=0) is rejected: it is not a
new peak. A candidate above a flat background needs no invented spread floor.
Without observed envelope frames the gate stays closed.

`BeatDetector.envelope_frames` is a read-only tuple of frozen
`OnsetEnvelopeFrame` values read immediately after the existing detector calls.
Combined/Superflux use the picker's existing raw ODF; Multiband uses each band's
raw ODF (including the existing uncompressed mid/treble raw-strength history).
No flux is recomputed and no candidate or picker state is modified by the tap.
CAP carries the tuple as `AudioFeatures.onset_raw_frames` in the next existing
publication, with each frame's own canonical sample position. It does not create
new publications or change contributor identities, candidate timing, or clocks.
Frames buffered before the first publication are retained and reset at epoch/DSP
reset. Combined and short mid/treble frames retain their 480-sample positions;
long bass frames use the same existing three-hop attack compensation as their
candidates. Multiband full reference uses the maximum available band raw value
at each tap position. Missing bands are absent, not manufactured zero values.

When a candidate has bass support, use its raw `onset_bass_strength` (or its own
strength for a bass-only candidate) against bass background + k × bass MAD.
Without bass support, use raw full strength against full background + full k ×
full MAD, where `onset_full_k` ≥ `onset_relative_k`. The Combined analyser has no
separate bass ODF; its full-band branch is used. No band is inferred from bars.

Both branches require strength ≥ the active detector's `onset_delta_abs`
minimum (default 0.02, in its existing raw units). `onset_refractory_ms` defaults
to 160 ms and is editable from 60 to 200 ms. Only fired accents start refractory;
all analysis frames continue training the background regardless of admission.
Reference and refractory use sample time / 48000, never wall time. The gate
retains one second of delivery slack for delayed candidates, but each reference
includes exactly [candidate−W,candidate], excluding future frames. Batched frames
and candidates are interleaved in sample order; duplicate event IDs cannot fire
twice. Epoch/mode/analyser-method/minimum changes reset admission state. Live k,
W, r and full k edits retain the existing analyser and envelope history.

The four settings are Energy Profile parameters in the existing Now Playing
row; k and full k are labelled in MAD units, not multiplicative envelope ratios.
The owner accepted k=8, W=3 s, r=160 ms, full k=9 as the published defaults
following the corrected sendback-4 sweep. Musical acceptance still fails:
Mau P has 587/797 ±50 ms hits (73.65%), 3.502 events/s and breaks [3,3,2,2];
Lou has 1.114 events/s and 54.50% coincidence. This is an explicitly accepted
failing setting, not a claim that a qualifying main/fallback point exists.

The 64× gain ceiling stays. The chosen Onset point does **not** meet the sprint-1
targets. It ships as a non-predicting fallback: **reacts to confirmed onsets;
does not separate kicks from hats**. It is not validated beat lighting. The
sweep found no gate setting on the current candidate stream meeting the targets;
that is a bench finding for sprint 3, not a reason for further tuning here.

New couplings default to **Tracker**, matching the owner's 2026-11-05 preference
for its more dynamic Mau P response. Schema 5 persists the mode explicitly.
Migration leaves every existing coupling's stored Off/Onset/Tracker value
unchanged; historical schemas before mode persistence retain their historical
Onset value when the migration materializes that previously absent setting.
There is no runtime mode fallback or silent migration.

The gain-tied floor is retired for Tracker too. Neither `onset_gain_floor` nor
`tracker_gain_floor` exists in schema-5 runtime models, API or controls. Migration
alone knows these retired names and removes the stored field (including the
unpublished schema-4 intermediate name). Tracker runs exactly as the old f=0
path: EnergyTrigger uses its original sensitivity base floor
`.08 * 2 ** ((50-sensitivity)/25)`, AGC capped at the Energy Profile ceiling,
log energy, adaptive ratio/mean, rise tests and refractory. No term depends on
gain to raise the floor. MusicalTimeline/TempoClock prediction remains Tracker-only;
the detector's candidate generation, timing and the tempo algorithm are unchanged.

The ticket's cited Tracker 760/797 result is the archived f=0.11 run; the actual
f=0 artifact is 756/797. The final report retains both provenance and miss bins
rather than relabeling 760 as f=0. No timing or Tracker estimator fix is included.

Installer migration upgrades schema 3/4 to 5, retires the gain floor, adds any
previously absent relative parameters with the accepted k=8/W=3/r=160/full k=9
values, and preserves every existing stored mode. It retains exact-byte pre-v5
backups and atomic replacement. Runtime rejects historical schemas and current
rows missing required settings; no runtime migration is installed.
