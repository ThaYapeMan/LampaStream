# Spotify Connect + direct Sonos output — revised architecture and plan

Revision note: this replaces the original SonosInboundSource sketch after an
external architecture review. The review's core corrections were checked
against the actual codebase (not just plausible on paper) and confirmed
sound — see "What changed from the original proposal" below.

## Decision

LampaStream remains a standalone application, reachable via multiple audio
ingresses (AirPlay, LMS, Spotify, others later) and able to drive a physical
Sonos speaker directly, without depending on the separate `sonos-squeezebox`
bridge repository.

## What changed from the original proposal

1. **Renamed SonosInboundSource → SonosOutputSink** (or, more generically,
   `PlaybackTarget` if a second output type is ever added). Sonos is a
   destination, not an ingress — the original name implied the opposite.
   Confirmed `VirtualPlayerType` (`models.py`) is exactly the ingress enum
   (LMS/AirPlay/Spotify); a Sonos concept does not belong in it. Sonos
   should not become a `VirtualPlayer` — sources and sinks are orthogonal:
   `AudioSource → AudioSession → PlaybackTarget`, which allows every
   combination (Spotify→Sonos, AirPlay→Sonos, LMS→Sonos) without
   player-specific branches.

2. **Branch PCM before analysis, not through it.** Checked directly against
   `sync_engine.py`: `CanonicalAnalysisPipeline` is constructed with
   `source=<PcmSource>` and **owns its own source-pull loop** internally
   (its docstring: "Owns the source loop, AudioCanonicalizer, epoch
   tracking..."). `player_manager.py` confirms one `PcmSource` object per
   ingress is handed straight to it. That means today there is exactly one
   consumer per source — routing Sonos output through or inside the
   analysis pipeline, as the original sketch implied, would genuinely
   couple two very different concerns:

   - Analysis: canonical resampling, sample-clock ownership, epochs, STFT,
     `AnalysisProcessor[]`, `PublicationRecord`, DSP timing.
   - Sonos playback: continuous PCM, network backpressure, FLAC encoding,
     HTTP connection lifecycle, buffering, pause/resume, device state,
     target latency.

   A slow Sonos connection must never block analysis, and analysis work
   must never interrupt playback. The fix is a small tee/fanout wrapper
   sitting *before* `CanonicalAnalysisPipeline`, implementing the same
   source protocol so the pipeline is unaffected, while a second consumer
   (`SonosOutputSink`) pulls independently. This is a low-risk insertion
   given `source` is already just a swappable object.

3. **The rejection of routing Spotify through `sonos-squeezebox` holds, for
   a stronger reason than originally stated.** It's not primarily about
   duplicating DSP in C++ (PCM could in principle be forwarded back into
   LampaStream) — it's that LampaStream would still depend on another repo
   for its core "standalone" promise. The direct Sonos sink belongs in
   LampaStream itself, full stop.

## Recommended architecture

````
AirPlay ─┐
LMS ─────┼→ AudioSession / PCM fanout ──┬──→ CanonicalAnalysisPipeline → Effects
Spotify ─┘                              │
                                        └──→ SonosOutputSink
                                                   │
                                          streaming FLAC / HTTP
                                                   │
                                         Sonos AVTransport (play_uri)
                                                   │
                                            physical Sonos
````

Key rule: **source != sink**, and **CanonicalAnalysisPipeline != playback
transport**. One canonical analysis path (as today), one optional playback
path, no dependency on `sonos-squeezebox`, and clean extensibility for
future sources/outputs.

## New concepts needed before any Sonos-specific code

### ActiveAudioSession

LampaStream needs explicit ownership of the currently active audio source
before Spotify is restored — otherwise source-transition races are likely.

````
ActiveAudioSession
  source = AirPlay | LMS | Spotify
  epoch
  PCM format
  playback state
  sink ownership
````

This doesn't need to become a large framework; its job is to answer
concrete questions: what happens if Spotify starts while AirPlay is
playing? What happens if LMS starts while Spotify is active? Which source
owns the Sonos sink? When does the analysis epoch reset? When is an old
source terminated? (e.g. Spotify starts → old AirPlay session ends → new
epoch → analysis resets → Sonos output switches generation.)

### Bounded, non-blocking Sonos fanout

````
                ┌── analysis consumer
PCM producer ───┤
                └── bounded Sonos queue → FLAC encoder
````

Not: `PCM producer → blocking Sonos write → analysis`. If Sonos falls
behind, use a bounded queue/ring buffer with a defined recovery policy
(e.g. queue overflow → reset output generation → reconnect with a fresh
stream) rather than accumulating unlimited audio in RAM.

## Reuse the behavioural lessons from sonos-squeezebox

The direct Sonos sink should reuse the transport invariants already proven
against real hardware this session, not copy the C++ code wholesale:

- Fresh FLAC header per connection.
- Stream generations (a monotonically increasing ID, not reused).
- Bounded encoder read-ahead (throttle a couple of seconds ahead of real
  time, not fully buffered).
- HTTP request lifecycle: plain `http://` URL with `play_uri()`, not
  `x-rincon-mp3radio://` (that scheme is for MP3 icecast-style radio and
  unproven here); a live/infinite stream rules out raw WAV, which depends
  on a fixed total length.
- Device-initiated pause/resume and SameURL restart behaviour — this
  session's `sonos-squeezebox` work (held-GET invalidation, `SameURL`
  reconnect, the resume state machine in `resume_state.h`) is the concrete
  reference implementation.
- **Don't reject every duplicate GET as a blanket rule.** Physical testing
  already showed Sonos legitimately creates a HEAD probe alongside an
  active GET, and separately opens held/speculative GETs around
  pause/resume. Model it as: stream generation N owns an active GET, a
  held/speculative GET, and HEAD/probe requests, and apply policy based on
  request type + generation + transport state — exactly the model
  `resume_state.h` had to evolve into through several iterations. Reuse
  that design directly rather than re-deriving it.

## Multi-Sonos shape

One shared HTTP server, but not one shared playback stream by default:

````
SonosHttpServer
   ├── Study        (own output session / encoder / generation)
   ├── Living Room   (own output session / encoder / generation)
   └── Kitchen       (own output session / encoder / generation)
````

Each physical Sonos can have different GET timing, read-ahead, HTTP
lifecycle, pause/resume behaviour, and latency. For an actual Sonos group,
control the group coordinator later rather than independently streaming to
every member — not designed yet.

## Latency correction

Real Sonos playback position (`GetPositionInfo`) is useful but should not
be the only source of truth for a live stream — it can be coarse, delayed,
or intermittently stale, and not perfectly aligned to the audible sample
position. Prefer a filtered estimator:

````
source PCM sample position → encoder/bytes served → Sonos GetPositionInfo
   → filtered playout-delay estimate
````

e.g. `estimated_playout_delay = source_sample_time - sonos_reported_play_time`,
smoothed or median-filtered, with a calibrated fallback delay (the existing
`PlayerLatency` concept) if the live estimate is unavailable. This could
later feed light-synchronization timing, not just Sonos-side correctness.

## Restoring Spotify without restoring the old dead end

The old Spotify integration (removed as commit `762edfa`) already solved
real, reusable pieces: Spotify Connect discovery, receiver integration,
configuration/UI, PCM production. Reuse those. What must not happen is
reverting it unchanged — its PCM must enter the new session/fanout model
from day one, not go nowhere as before:

````
old Spotify implementation → reuse receiver/discovery/config/UI → PCM producer
   → new AudioSession fanout (analysis + SonosOutputSink)
````

## Phased plan

**Phase 0 — audio session/fanout boundary (no Spotify work yet).** Define
active-source ownership, PCM fanout, sink isolation, the bounded Sonos
queue, and epoch/lifecycle behaviour. This is prerequisite infrastructure,
not a Sonos feature.

**Phase 1 — direct Sonos output, proven with an existing ingress.** Build
`AirPlay or LMS → PCM Session → SonosOutputSink → FLAC → HTTP → physical
Sonos`, applying the reused `sonos-squeezebox` invariants above. Prove
audible playback using AirPlay or LMS, independent of Spotify entirely —
this validates the new output path on its own.

**Phase 2 — restore Spotify Connect.** Revert commit `762edfa` (or
cherry-pick `230633d` + `0728aaf` back), then route its PCM into the exact
same session/fanout layer built in Phase 0/1. This is what actually fixes
the original "visible in Spotify, no sound" problem — the endpoint reused,
the output path new and real.

**Phase 3 — state/control synchronization.** Play/pause/volume/track
changes/disconnect/reconnect, Sonos device-initiated state changes —
reusing the lessons from `sonos-squeezebox`.

**Phase 4 — groups/coordinator behaviour.** Add Sonos group-awareness when
grouped: target the group coordinator rather than independently streaming
to every member, unless a proven need for the latter emerges. Not designed
yet.

**Phase 5 — live latency feedback.** Use the filtered playout-delay
estimate to improve light synchronization timing, beyond just Sonos-side
correctness.

## Open questions

- Exact scoping: does `SonosOutputSink`/`PlaybackTarget` become a new
  first-class concept alongside `VirtualPlayer`, or an infrastructure/
  configuration concept that stays internal for now while the existing
  six-entity public model is preserved? Needs a decision before Phase 0
  (per `CLAUDE.md`'s boundary that registry definitions, not
  player-specific branches, own engine construction).
- Whether `ActiveAudioSession` is a new persisted entity or transient
  runtime state only.
