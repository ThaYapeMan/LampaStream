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
