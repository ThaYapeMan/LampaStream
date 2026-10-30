# AirPlay progress investigation — BATCH-01 send-back 1

Architecture check: canonical PCM → one analyser → renderer/scheduler → outputs.
Progress, metadata identity and duration stay in `track_position.py`; per-kind
sample-to-room-time mapping stays in `audible_clock.py`. No AirPlay branch was
added downstream.

## History and field evidence

`be3de77..25aedb4` has no changes to the metadata reader, player manager,
Shairport setup, socket delivery or TrackProgress component. In
`25aedb4..8d886f7`, the manager selects new AudibleClock implementations and the
native LMS play clock; progress parsing, delivery and receiver configuration are
unchanged. Neither inspection establishes a first-bad commit. The field state
and event order matter, so a version correlation alone does not prove causality.

The owner journal `/home/codex/src/sps.txt` shows Apple Music buffered stream type
103 and actual **pipe** writes in this order: `pbeg`, `pres`, `prgr`, DMAP
`mdst`/`mper`/`astm`/title/`mden`, a metadata refresh, another `prgr`, another
metadata refresh, then `phbt` heartbeats. Thus buffered sessions do supply
progress; this is not a receiver-wide absence of progress. The journal records
progress lengths but not the three RTP values. `airplay-timing.json` was absent;
it would have supplied those values and receiver-reader timing generations.

## Reproduced player-reader defects and fixes

- The first title batch cleared an existing progress anchor because the earlier
  playback-only snapshot had `title=None`. Keep that newly supplied anchor.
- Pre-roll progress with current RTP before start was interpreted as a huge
  unsigned elapsed value and discarded. Retain a signed wrapping RTP anchor,
  with position zero until the track start becomes audible. Preserve its future
  monotonic anchor across metadata updates; subsequent heartbeats correct it.
- `core/astm` (big-endian milliseconds) was ignored. Decode duration in the player
  metadata adapter. `core/mper` (persistent identity) distinguishes a new track,
  even if its title is unchanged, and clears old progress when no replacement
  anchor was supplied. Do not invent position when no track origin is known.

`tests/test_airplay_progress.py` reproduces these defects before the fix and
checks progress/duration after the journal's event ordering. Numeric payloads in
the tests are representative, not claimed to be a capture from the journal.
Existing wrapping RTP, pause/resume/end, LMS status and ROUTE-01 audio-clock tests
pass unchanged. UI and preview use the same generic track contract.

Mid-track activation has a separate lifecycle issue: it opened the metadata
reader only for an active AirPlay coupling and unconditionally invalidated its
cache after receiver preparation, even if the receiver never restarted. Send-back 2 fixes this by keeping the receiver's single PCM reader and metadata
reader manager-owned in standby, with exclusive read handoff to analysis. The
regression test also reproduces an EPIPE when the previous session closed the
only audio reader under a still-playing receiver; keeping that descriptor alive
and draining prevents the receiver from losing its output. Neither condition can
be repaired by fabricating progress in the UI.

Owner acceptance remains necessary: Apple Music position/length on the deployed
receiver, with LMS unchanged. Raw diagnostic progress values are needed to prove
which of the reproduced cases explains every field symptom; no unsupported
culprit commit is named.
