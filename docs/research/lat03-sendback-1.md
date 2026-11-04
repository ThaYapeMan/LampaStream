# LAT-03 send-back 1: content clocks rather than seek labels

Base: d76778e. Evidence: both 2026-11-02 owner captures and journals, compared
with the 2026-11-01 capture. Journal times are CET; manifests/packet epochs use UTC.
No analyser, tempo-clock algorithm, renderer, scheduler or output driver changes.

## LMS: the 50 ms difference is in the FLAC seek landing

The packet captures contain both the CLI seek command and the first FLAC frame
returned for the virtual player's new HTTP stream:

| Run | Requested seek | First FLAC sample | Actual content time | Requested − actual |
|---|---:|---:|---:|---:|
| 0940 | 6.316 s | 278528 | 6.315827664 s | 0.172 ms |
| 1022 | 6.273 s | 274432 | 6.222947846 s | 50.052 ms |

Both FLAC streams have 4096-sample blocks at 44.1 kHz. That is a **49.880 ms**
difference between the seek-label errors, explaining the approximately 50 ms
settled offset difference. The decoder emitted each complete first FLAC frame;
it neither skipped samples to the requested fractional position nor exported
the frame's true content position. Own-player CLI time retained the requested
seek label. A relative position-pair estimate cannot distinguish this error.

0940: startup delay 111 ms; seek at 09:27:33.062; first journal consensus at
09:27:50.468 sets target −69 ms while applied remains 111 ms. Subsequent targets
are −64, −61, −59, −58, −57, −46, −36, −25, −14, −4, +17, +24, +32, +39, +57,
+65, +74, +89, +96, +107, +115, +133, +141 ms. The final persisted target is
+141 ms, from the existing unconditional persist after accepted consensus.

1022's supplied journal begins at 10:09:02, after startup. Its seek is recovered
from the packet trace at 10:08:42.485: 6.273 s. Replaying the captured position
pairs against d76778e reconstructs first consensus at 10:08:56.825, target −69 ms,
starting from the preceding saved +141 ms. At the journal's first line the
applied value is 110.621 ms and target −60 ms, consistent with 5 ms/s since
that first consensus. It reaches −48 ms by 10:09:48, then targets −36, −31, −25,
−17, −11, −1, +7, +15, +23, +32, +42, +60, +70, +79, +87, +96, +103, +112 ms.
The final saved value is +112 ms. Packet-based midpoint reconstruction differs
from journal rounding by at most about 1 ms; it is labelled reconstruction,
not an invented missing journal segment.

## New estimation basis

At LAT-03 acceptance, the pinned yeney-core sources remained pristine and the
installer applied a local content-position patch to its isolated build.
Upstream `dc8cf3a` now supersedes that patch; the installer builds it directly.
libFLAC already converts frame numbers to absolute sample numbers. The patch
retains that first sample number, carries current content position through the
player sink, and uses the existing YNPT tail's last 12 reserved bytes:
`content_frame` (uint64) and `content_flags` (uint32, bit 0 = known). The v1 PCM
prefix, timing-block size and existing fields remain unchanged. Crossfade output
is not labelled as unmixed content. Unsupported codecs do not invent a position.
Installed provenance records and verifies the exact patch hash plus binary hash.

The Python SHM reader publishes a verified content clock `(q, n, q_start)`:
actual track position q at native monotonic time n, and actual first content
position q_start. Only coherent copies with the capability flag supply it.
For CLI own/follow positions p_o, p_r measured at midpoint times t_o, t_r:

```
r       = p_o - p_r - (t_o - t_r)
landing = requested_seek - q_start
b       = t_o - n + q - p_o + landing
saved   = median(b)*1000 + playDelay
applied = saved + estimate(r - landing)*1000 + trim
```

The session's relative position and frame-boundary error stay in the live
session term. They are not persisted as a property of the room. Combining the
terms cancels the own player's seek label entirely, giving the room's reported
position-to-native-content mapping. Four jointly plausible position/native-clock
samples establish consensus. Old numeric estimates lack the new
`measurement_basis=lms-content-v1` tag and are not reused as stable room values.

There is one startup step per track, with a fresh consensus in the first 15 s.
The first session's deadline starts at probe creation; ordinary notifications,
outlier-window resets and trim edits cannot extend it. New track notifications
start a new track window. Sampling starts after one second and bursts every
second. Later corrections remain bounded at 5 ms/s. A startup step advances the
clock generation once so pending pre-calibration scenes are retired. Slewing
does not repeatedly invalidate queued work. Status remains `measuring`, not `stable`
(“In sync”), until applied and target differ by less than 15 ms. Missing content
provenance cannot produce a false stable result.

Tests cover both captured seek landings with the same 12 ms physical calibration,
including reuse in the second session, correct mapping before its first locked
beat, no second/late startup step, and the later 5 ms/s bound. A compiled patched
producer streams two real frame-aligned FLAC fragments through SHM and verifies
their absolute origins against ffprobe packet timestamps. No fake content label
substitutes for that native boundary check.

## AirPlay: what the evidence establishes

The first ten seconds of L16 RTP PCM have the same SHA-256 in all three captures:
`cc1aa40f283147c68070677d73d5b3fb3c2f26906bc5977c62aa9f63e3750d28`.
Sender RTP starts at 66150 in all runs. Metadata origin minus the RTCP timing
origin is −743.139 ms yesterday, −743.515 ms in run 1 and −743.553 ms in run 2:
less than 0.5 ms change, rather than 60 ms. This rules out a 60 ms change in
sent content and in that metadata origin relative to sender timing.

The clock formula and the AirPlay metadata class were not directly changed by
LAT-03; slewing was confined to the LMS class. A pin generated with the actual
82181c5 clock/source/logger produces 67 non-predicted synthetic 128 BPM detections
on the real WebSocket producer. The current producer/logger matches those
track seconds with **0.000000 ms** maximum difference (2 ms acceptance). The
pinned values are committed so shallow CI checkouts do not need Git history.
The logger's alias columns therefore do not explain the observed field shift.

The old mapping combined native PCM playback time with a metadata-receipt-derived
track anchor. Any change in their relative clock calibration appears directly
in `detected_audible_t`. The new AirPlay track origin uses the exact tapped RTP
sample/play-time pair used for PCM provenance. Metadata supplies track identity,
start RTP and duration; it no longer supplies an independent receipt-time clock
when the native RTP clock is available. Pre-roll, wrap and generation invalidation
remain explicit. Pipe fallback retains the old metadata behavior. Tests inject
±60 ms metadata delay and a +60 ms native-clock shift: track seconds remain fixed.

Peak reductions also moved out of the primary source read into the diagnostic
getter. They retain frame identity and timestamps and add no PCM buffering stage.
Captures now preserve preview status (track anchor, source/latency state and trim)
in `*-status.jsonl` to resolve any future clock/configuration ambiguity.

**Attribution limit:** the supplied archives do not record the old native tap
clock pairs or active AirPlay trim/configuration. They do not prove which runtime
clock calibration or scheduling change exposed the 60 ms difference. No specific
d76778e line is claimed to introduce a deterministic +60 ms formula. The fix
removes the mixed-clock dependency; it does not insert an unmeasured −60 ms trim.
A new field capture must verify physical timing, not just the pinning test.

## Reference deployment and acceptance

The owner's timestamps-only beat CSV and summary are committed under
`tests/fixtures/ab-references/mau-p-jalbm/`. The bundled title aliases are the
last lookup candidate after explicit `AB_REFERENCE_BEATS`, the track's adjacent
CSV, existing `own/<slug>` locations and artifact/fixture candidates. Other tracks
continue to use `AB_REFERENCE_BEATS` or their own local reference. No audio is
committed. The exact selected CSV is copied into each archive.

Owner acceptance is still two consecutive same-track captures: both LMS runs
within ±40 ms from the first bin, adjacent medians changing by <20 ms, saved room
calibration differing by ≤10 ms; AirPlay back to its prior range. Deployment must
use the standard installer so the content-position producer patch is built.
