# Automatic AirPlay light timing

## Evidence and timing contract

Inspected upstream shairport-sync at the installer pin
[`0b1c4391ffd398e7b145eb4b98416261380adeea`](https://github.com/mikebrady/shairport-sync/tree/0b1c4391ffd398e7b145eb4b98416261380adeea).
These references describe that revision, not an assumption about later releases.

* The pipe backend ignores its RTP timestamp and local play-time arguments. It
  writes synchronously, with no backend queue or delay callback
  ([audio_pipe.c, lines 64–106](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/audio_pipe.c#L64)).
  The FIFO is opened nonblocking to find a reader, then changed to a blocking
  writer ([common.c, lines 1505–1535](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/common.c#L1505)).
  Between network decoding and the write, the player's decoded-packet ring
  waits for each frame's local play time minus the desired backend buffer
  ([player.c, lines 1372–1490](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L1372)).
  Consequently synchronised steady-state output **is paced**. Missing timing or
  timestamps beyond the ten-second sanity bound bypass the wait; this is why
  runtime delivery checks remain necessary. The pipe's default desired
  buffer is one second; kernel FIFO buffering and a slow reader can add latency.
  Startup is different: the no-delay backend receives lead-in silence rapidly
  ([player.c, lines 1332–1357](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L1332)).
  A three-second observation window after first-frame/resume events prevents
  treating that initial burst as evidence of steady delivery.
* The seconds-valued offset is assigned without a range check. The **deprecated
  integer** option alone has a ±66150-frame (±1.5 s at 44.1 kHz) check
  ([audio.c, lines 130–230](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/audio.c#L130)).
  Do not apply that integer limit to the seconds option. Its practical range
  depends on sender runway and packet buffering, signed frame conversion and
  the player's ten-second timestamp sanity check. Very large values are not a
  useful or safe timing contract.
* AirPlay 2 realtime adds the offset to the notified latency, including the
  11035-frame protocol adjustment, and moves the PTP anchor by that signed
  number of frames. Non-positive computed notified latency emits a warning and
  uses nominal latency; the anchor still includes the offset
  ([rtp.c, lines 1805–1840](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/rtp.c#L1805)).
  Buffered streams subtract the signed offset from the supplied anchor RTP time
  ([rtsp.c, lines 1980–2005](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/rtsp.c#L1980)).
  Both honour a negative offset: negative means earlier delivery; positive
  means later. The desired backend buffer adds a further early lead.
* `prgr` contains start/current/end wrapping 32-bit RTP frame positions, without
  a local timestamp, at the sender's update cadence
  ([rtsp.c, lines 3650–3750](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/rtsp.c#L3650)).
  `pffr` marks the first validly timed frame, without a payload
  ([player.c, lines 1199–1220](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L1199)).
  `phb0` and `phbt` carry `RTP/local_playtime_ns` immediately after the first
  timed write; `phbt` then follows `metadata.progress_interval` (10 s in the
  managed configuration)
  ([player.c, lines 3116–3222](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L3116)).
  On Linux these nanoseconds use `CLOCK_MONOTONIC_RAW`, not Python's normal
  monotonic clock ([common.c, lines 1458–1470](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/common.c#L1458)).
  The tap captures both clocks; the probe compares play time with the raw clock
  captured at the metadata event, rather than subtracting unrelated clocks.
* Pause/resume (`paus`/`pres`) disable/re-enable buffered playback and reset the
  anchor ([rtsp.c, lines 2009–2046](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/rtsp.c#L2009)).
  Flush/seek sends `pfls` with the cutoff RTP timestamp and discards player
  buffers ([player.c, lines 3565–3577](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L3565)).
  The pipe has no flush callback, so bytes already in the kernel FIFO cannot be
  withdrawn. Track metadata batches (`mdst`/`mden`) do not guarantee a flush or
  a new timeline. Session end stops the player and resets anchors
  ([player.c, line 1829 onwards](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/player.c#L1829));
  the pipe stop callback itself is a no-op. The tap resets on playback/flush
  lifecycle events, retains track timing across metadata-only changes and
  pauses on end/EOF. It never infers a timeline from track text alone.

## Incident on 2 October and corrected defaults

After installing 145d0bc, the owner's AirPlay stream produced no pipe audio:
preview was black, Hue output stopped and Light timing said “Audio delivery
stalled”. The journal contained the owner's evidence:

```text
"player.c:1130" Dropping out of date packet 4832 with timestamp 1435647391. Lead time is 0.090227 seconds.
"player.c:1153" Check packet from buffer 4836, timestamp …, 0.002134 seconds ahead.
"rtp.c:2547" sleep while full
```

The configuration contained:

```conf
audio_backend_latency_offset_in_seconds = -0.5;
audio_backend_buffer_desired_length_in_seconds = 0.0;
audio_backend_buffer_interpolation_threshold_in_seconds = 0.0;
```

Removing those three lines and restarting shairport-sync restored audio and
lights immediately. This sender's runway was about 0.1 s. Requesting audio
0.5 s early moved packets outside that runway; the presumed spare margin was
not available. Processing time P is not evidence of sender headroom.

Fresh installations impose none of these settings. Upgrades remove only the
exact legacy numeric values above, preserving different operator values and
unrelated settings. Duplicate, malformed or deprecated timing settings are
refused before writing. The installer retains its validated, fsynced atomic
replacement with ownership and mode preservation. The manifest records
`airplay_delivery_margin_ms: 0`, `airplay_timing_policy: receiver-defaults` and
the pinned receiver revision; verify-install checks this policy and rejects
remaining legacy values while allowing preserved operator settings.

M is conservatively **0 ms** with the receiver's own defaults. The backend's
own default desired buffer remains one second, as upstream defines it; this
is not a certified advance against what a particular group audibly plays.
LampaStream adds no early-delivery offset and makes no assertion that an
arbitrary sender has spare runway. Operator timing overrides are unverified.
On the regular-pipe fallback, with steady Auto measurements, no deliberate delay and processing P, the card
says “Lights are about P ms behind the sound”, with a “Lights behind” pill.
Positive fine-tune adds to this reported lag. Earlier is disabled at zero;
negative saved trim cannot advance the output. A previous 500 ms measurement
is never reused as a delay when M is zero.

## Timestamped early PCM tap

Normal pinned logs and metadata do not expose continuous arrival headroom.
Startup “Lead time for first frame” values of 0.26–1.97 seconds from Apple Music
are not steady-state evidence. The new tap copies audio that has already been
decoded; it neither advances receiver playout nor requests packets earlier.
`audio_backend_latency_offset_in_seconds` is not used or changed by this feature.
The history of the −0.5 second failure above remains relevant to that separate
receiver setting.

The installer applies `shairport-sync-0002-early-tap.patch` after 0001, at the
same exact pin, with forward and reverse checks. The installer alone enables
`pipe.early_tap_name = "/run/lampastream/airplay-early.pcm";` through the existing
validated, atomic configuration update. It provisions a second 0600 FIFO owned
by lampastream. Name changes preserve this key; activation never edits it or
restarts an unchanged receiver. The installation manifest records wire version
1 and the patch SHA256; verification checks the key and FIFO.

### Earliest decoded audio and clock references

Line numbers below refer to the unpatched pin:

- **Realtime**, including AirPlay 2 realtime and AirPlay 1:
  `player_put_packet()` in player.c:463–565. The tap follows successful
  `audio_packet_decode()` at lines 539–547, where `abuf->data`, `datalen` and
  `actual_timestamp` are all available, before the player buffer waits for
  playout. Resent and out-of-order packets are marked, rather than reordered.
- **AirPlay 2 buffered AAC**: `rtp_buffered_audio_processor()` in
  rtp.c:2223–3020. After `swr_convert()` and the existing delayed-flush truncation,
  immediately before the PCM-buffer copy at lines 2978–2982, `pcm_audio`,
  `dst_bufsize` and `expected_timestamp` identify the decoded audio and RTP frame.
  This precedes the buffer's playout gate at lines 2537–2670. The later
  `player_put_packet(original_format=0)` is deliberately not tapped again.
- `frame_to_local_time()` in rtp.c:3034–3042 dispatches to
  `frame_to_ptp_local_time()` (1467–1485) or
  `frame_to_ntp_local_time()` (1120–1145). The tap uses these existing anchor
  conversions without a new timing calculation or latency adjustment.
- `get_absolute_time_in_ns()` in common.c:1458–1470 uses
  `CLOCK_MONOTONIC_RAW` on Linux. The writer takes that clock and then
  `CLOCK_MONOTONIC` back to back for every record. Python maps the scheduled
  time as `mono_write + (play_raw - raw_write)`. It never subtracts unrelated
  clock domains or assumes a constant offset across sessions.

The observational tap accepts 44,100 Hz, 16-bit stereo. Other decoded formats
are dropped and use the existing pipe conversion/fallback. The original pipe
backend and its volume, format conversion and timing remain unchanged.

### Record format and bounded writer

Wire version 1 uses a **52-byte little-endian header**:

| Offset | Field | Bytes |
| --- | --- | --- |
| 0 | Magic `LSET` | 4 |
| 4 | Version `1` | 2 |
| 6 | Flags: flush=1, pause=2, resume=4, discontinuity=8, out-of-order=16 | 2 |
| 8 | Wrapping RTP frame number | 4 |
| 12 | Stereo-frame count, 0 for a control marker | 4 |
| 16 | Wrapping generation number | 4 |
| 20 | Scheduled play time, shairport clock nanoseconds | 8 |
| 28 | Write time, shairport clock nanoseconds | 8 |
| 36 | Paired CLOCK_MONOTONIC nanoseconds | 8 |
| 44 | Cumulative dropped-record count | 8 |

PCM follows in S16_LE stereo, four bytes per frame. Larger decoded blocks are
split into at most 1,000 frames, so each write is at most 4,052 bytes: below
Linux PIPE_BUF=4,096. Each non-blocking write is therefore atomic, including
when a reader is slower than real time. No reader, a full FIFO or a contended
tap lock drops the record; it never waits for the consumer. SIGPIPE is already
ignored by pinned shairport-sync. Failed writes advance the generation, so a
lost control marker cannot silently join two later audio timelines. The counter
is carried in records and logged at most once every 30 seconds while events
are arriving; this does not increase receiver debug verbosity.

Flush, pause and resume hooks are `do_flush()`, `player_play()`, `player_stop()`,
`handle_flushbuffered()` and `handle_setrateanchori()`. RTP gaps and anchor
jumps exceeding 50 ms mark discontinuity. A record retains the generation of
its write operation; an old generation cannot undo a later flush. Marked
out-of-order records and duplicates are ignored by the reader, with signed
wrapping RTP comparison. Existing production metadata lifecycle events also
invalidate pending scenes independently. Buffered delayed flushes conservatively
invalidate the entire pending light timeline, rather than displaying audio
that the sender may have cancelled.

### One reader, one analysis path, automatic fallback

One `EarlyAirPlaySource` owns both FIFO descriptors. While the tap is healthy,
regular PCM is drained and discarded through its sole reader, keeping the
unchanged blocking pipe writer flowing. Only tap PCM enters the canonical
analysis pipeline. Diagnostic consumers use the existing in-memory tee; they
never attach another reader to either production FIFO.

Missing tap data, a malformed record, or more than one second without fresh
PCM switches to **pipe fallback**, without touching the receiver. Records that
have already spent over one second in the FIFO are stale too. Source transitions
log once, invalidate DSP provenance and discard pending scenes. The reader keeps
watching the tap and returns automatically when valid, fresh records arrive.
A missing FIFO is retried once per second. Memory is bounded; partial records,
queued tap records and scenes do not grow with playback duration.

### Measured lead, scheduling and the existing card

Lead is the mapped play time minus **reader receipt**, so FIFO residence and a
slow consumer reduce the measured lead. The session keeps rolling p5 and p50
percentiles over the latest 1,024 records, resetting on lifecycle/source changes.
No startup log, saved measurement or guessed sender margin supplies this lead.

PCM is analysed on arrival through the existing canonical pipeline. Play time
and generation propagate through resampling and publication intervals; processor
and DSP algorithms are unchanged. The existing 30 Hz output loop renders newly
published intervals and queues their scenes at play time plus fine-tune. At each
tick it sends the newest due scene, not a burst of stale output. The queue holds
at most 1,000 scenes. Already-past targets send immediately. Spatial effects use
the effective display time so an Earlier trim cannot create a negative-age,
black scene, and a late scene is not artificially faded before its first send.

Auto uses the measured lead. Earlier is limited to `max(0, p5 lead − P)`, with
the existing ±1,000 ms outer bound and 10 ms UI steps; the scheduler enforces the
bound again if lead decreases. Fixed adds its chosen delay to the scheduled
play time; None adds no intentional delay. Pipe fallback keeps the existing
non-negative delay behaviour. Processing P excludes the intentional queue wait.
Flush, pause, discontinuity and source changes discard scheduled scenes.
Hue ownership, five-second keepalive, idle_timeout=0 and output recovery from
78b9c84 remain while playing. Couplings now release after the configured idle interval;
re-acquisition clears old scenes without changing early-tap generations.

The existing Light timing card says **“Lights on time”** when p5 lead ≥ P,
otherwise **“Lights about N ms behind”**, where N = max(0, P − p5 lead).
Details show “Audio arrives about X ms early (p5 Y ms)”, the active source and
tap drop counter. Pipe fallback says that audio arrives at playout time. Lead
never includes a presumed early-delivery offset or the sender's startup runway.

### Local verification and build limitation

`python3 scripts/check-airplay-patches.py <upstream-clone>` checks both patches
against the exact pin in order, then checks both already-applied paths. These
checks passed locally. The actual new C writer is compiled with
`cc -std=gnu11 -Wall -Wextra -Werror -pthread` in the framing tests, with only
configuration/clock stubs; real FIFOs verify no-reader and full-FIFO dropping.
Python fixtures cover the clock-domain offset, four lead regimes, control events,
wrapping/out-of-order RTP, malformed/stale data, fallback/recovery, bounded slow
consumers, native publication timestamps and the production 30 Hz output loop.

A complete receiver build could not run in this development environment:
`autoreconf` and the libconfig, FFmpeg, plist, Avahi and gcrypt development
packages are absent, and `sudo -n true` requires interactive authentication.
The documented substitute is sequential `git apply --check`, reverse checks,
and the compiled actual writer/framing test. No receiver was installed or
started, and no LXC was accessed. The owner must run the normal installer build
on their system before exercising live senders; synthetic leads are not a claim
about measured headroom on the owner's iPhone.

The installer sets neither `-v` nor `diagnostics.log_verbosity` nor the deprecated
`general.log_verbosity`. The [pinned default](https://github.com/mikebrady/shairport-sync/blob/0b1c4391ffd398e7b145eb4b98416261380adeea/shairport.c#L396)
is debug level 0. The mutex/flush debug messages therefore come from an external
verbosity setting or invocation; no managed verbosity needs reducing, and
operator choices are preserved.

## Runtime safety rollback

During an active AirPlay coupling, a watchdog checks every 0.5 s. Playback
begin/resume or a valid timed-write heartbeat establishes independent playback evidence;
pause, flush and end clear it. Pipe EOF cannot erase that evidence. If no PCM
has arrived for **more than three seconds**, measured from the later of playback
begin and last arrival, and a validated negative seconds-valued offset exists,
LampaStream removes it and the exact legacy zero buffer values. Other operator
values remain untouched. It flushes the existing service-owned configuration
file and uses only the existing narrow `systemctl restart shairport-sync`
authorisation. The service cannot atomically replace files in `/usr/local/etc`;
runtime uses the same file-only permission as receiver-name editing, whereas
installer upgrades retain atomic replacement.

The manager marks the attempt before writing or restarting: there is exactly
one recovery attempt per application lifetime, including on failure. A restart
operation is awaited even if teardown cancels its task, so it cannot finish
later against a replacement session. Successful recovery clears timing and
metadata, switches Auto to M = 0, logs one warning and displays:
“Early delivery was too much for this sender and has been switched off”.
Write/restart failure reports a recovery failure without claiming success or
retrying. A stopped, paused, healthy or default-offset session never triggers
recovery. No physical receiver was accessed during development.

## Activation regressions observed on 2 October 2026

The owner's production evidence after 9ba8354 showed every AirPlay activation
at 14:12:44, 14:14:30, 14:17:21, 14:18:13 and 14:19:54 ending Hue Entertainment
exactly ten seconds after startup without a LampaStream deactivation. The first
LMS activation at 14:10:45, with Auto delay 3094 ms, did the same. Now Playing
continued showing analysed audio after light output died. A later LMS activation
with zero delay and music already playing kept streaming until deactivation.
The session library's default ten-second idle monitor had permanently stopped
DTLS before delayed audio or the first sender arrived; later sends were no-ops.

The same logs showed an unchanged receiver restarted on every AirPlay Go.
shairport-sync exited on SIGTERM and terminated the live iPhone player at
14:17:12 and 14:19:45. The iPhone reconnected only 50–90 seconds later. A forced
restart therefore caused, rather than repaired, a long ingress gap.

## Hue output ownership and recovery

HueDriver still uses `EntertainmentSession(..., idle_timeout=0)`. The installed
`hue-entertainment` 0.1.2 sender resends its last frame every five seconds; this
keeps the bridge stream alive while music starts, plays or fills the delay buffer.
The library's own idle monitor stays disabled. Idle ownership is now a coupling
policy, rather than a library timeout: `release_after_idle_s` defaults to 30
seconds, with 0 disabling idle release. Pause, stop or absent new analyser
publications count as idle. The two-second health loop checks this policy; gaps
shorter than the configured interval retain their existing visual behaviour.

Local connection failure still recovers with 1/2/5/10-second backoff, capped at
10 seconds. Local `is_streaming` is checked every two seconds. Remote status and
streamer identity are checked every ten seconds, with a five-second timeout.
Remote inactivity or changed ownership triggers recovery only if a local
connection failure is present or a send/handshake failure was recorded within
15 seconds. Otherwise it is an external release: no recovery is scheduled.
The local connection closes without sending the library's area-stop REST call,
which would otherwise stop the new controller. The library lacks a public
local-only disconnect; the driver clears its internal area ID before `stop()`.
Idle/explicit release then uses its own bounded area-stop REST request; external
release omits it. Ownership is checked again immediately before idle release,
so a takeover between the regular polls is respected.
A test exercises this adapter against the installed library. REST verification
failure alone does not authorise recovery.

Idle release resumes automatically on fresh audio, resumed playback or a new
track, after checking all entertainment areas on the bridge. Another controller
leaves output released. Automatic recovery and re-acquisition always call
`start(stop_others=False)`. Only Go/Start and Take lights may stop other areas.
External and explicit release stay released until Take lights or a new explicit activation;
continuing audio never takes the lights back. Scenes produced during release
and re-acquisition are discarded. An output generation clears the early-tap
scene schedule and regular delay buffer across ownership changes, independently
of the tap's existing flush/discontinuity generation.

`on_release` selects restore (default), off or leave. Restore snapshots each
area light before initial start and each re-acquisition, then restores on idle,
external release or Stop. Off applies to idle, Release lights and Stop; external controllers
retain their choice. Leave performs no release-state REST writes. Snapshot and
release operations use asynchronous Hue v2 REST, three seconds per request and
a ten-second total budget per operation (including the area stop on release).
Failures warn and do not block the light loop or prevent shutdown. Recovery retains the original ownership snapshot. End-state actions run once
per ownership interval; Stop or close after release does not repeat them.

`output_status` in `/api/status` and the preview websocket includes `released`
alongside streaming, reconnecting and failed, with a plain-language reason.
Now Playing always shows a Lights row for an active coupling: Release lights
while streaming or reconnecting, and Take lights while released. Explicit
release cancels recovery and does not resume automatically on audio or track
changes. The status includes its explicit, external or idle release kind. Analysis may continue while the
lights are released, but `bridge_connected` remains false.

Health, remote-check and recovery tasks are cancelled and awaited on teardown.
An in-flight library handshake/disconnect executor is also awaited before a
replacement stream is allowed. Reconnection is for output failure, never for
silence. Tests use fake sessions and clocks; no physical bridge was accessed.

## Coupling switching without interrupting the sender

Every switch still closes the old metadata reader, awaits session tasks, stops
analysis before releasing PCM, stops the latency probe, closes Hue DTLS and
reaps yeney-player. The new AirPlay activation opens its sole FIFO reader,
checks the receiver service, invalidates track metadata, resets timing and
discards bounded queued PCM, regardless of whether the configuration changed.
These are LampaStream-side resets and do not touch the iPhone session.

The pinned pipe backend retains its writer descriptor and writes to the same
FIFO. A newly attached reader allows that writer to deliver again. The existing
reader-side EOF handling keeps metadata attached while a writer reconnects;
no receiver restart is needed to repair this state. Discarding pending bytes
happens before the analysis worker starts, through the sole production reader.
Track details may await fresh metadata, but PCM does not depend on receiving it.

An unchanged, active service logs “AirPlay receiver kept running (configuration
unchanged)” and runs no start/restart command. `systemctl is-active shairport-sync`
is read-only. A stopped service is started; a changed rendered configuration
restarts a running service exactly once. That restart logs a WARNING that any
connected sender will be interrupted. The existing polkit rule now permits only
`start` and `restart` on this same service for the LampaStream account, with no
broader service-management permission. The early-delivery safety rollback retains
its one restart because it changes the configuration.
Service preparation failures refuse activation rather than reporting a ready
receiver; service commands are not retried within that activation.

The switch log remains `coupling switch: <from> → <to>: source opened / receiver
ready / DTLS connected`. “Receiver ready” means running and available to the
reader, not restarted. LMS commands, measurement, yeney-core and DSP algorithms
remain unchanged.

## Processing measurements

P starts immediately after the sole PCM reader's `os.read`, before conversion.
The monotonic timestamp follows source sample intervals through resampling and
analysis into the rendered scene. P ends when `HueDriver.send` returns after
handing the scene to the Hue session. Deliberate queue residence between scene
ready and send start is subtracted: otherwise the applied delay would feed back
into the estimator. P includes conversion, analysis buffering/scheduling,
rendering and synchronous Hue dispatch; it cannot measure network delivery or
the physical lamp response. Per-player fine-tune covers those remaining effects.
No audio algorithm or LMS commands change.

The last seven accepted P values provide a median and scaled MAD precision
(1.4826 × median absolute deviation). Non-finite/negative values and jumps over
400 ms from the current median are rejected. Three consecutive large changes
start a fresh window, so a sustained processing change cannot leave an old
estimate in place indefinitely. The untrimmed delay is `max(0, M − median(P))`; applied delay is
`max(0, untrimmed_delay + trim_ms)`. At M = 0 it is therefore never negative. After the first steady value, each newly accepted
measurement moves the delay by at most 50 ms. The last good untrimmed value is
saved at most every 15 s and on orderly stop. Fine-tune updates immediately in
the UI; application follows the same step limit.

## Runtime pacing and read-only probe

Both runtime and probe use `CadenceCheck`: three complete one-second windows,
44,100 frames/s within ±5%, arrival p95 jitter ≤20 ms, no gap over 100 ms and no
read burst within 1 ms containing over 100 ms of audio. Jitter is the absolute difference
between a read interval and the preceding read's audio duration. Faults are
visible immediately; recovery requires three healthy windows. Reader scheduling
and FIFO coalescing are included, so this is a conservative delivery check,
not proof of absolute PTP synchronisation.

Activate an AirPlay coupling and play audio, then run on the LampaStream host:

```sh
/opt/lampastream/.venv/bin/python scripts/airplay-timing-probe.py --duration 60 --output /tmp/airplay-timing.jsonl
```

Use the installed release's Python if its path differs. The script defaults to
`http://127.0.0.1:8420/api/airplay-timing`; `--url` overrides that diagnostic URL.
It polls once per second and copies bounded diagnostic events from the existing
PCM and metadata readers. **It never opens either FIFO**, receives no audio and
cannot steal production bytes. The API is GET-only. A stopped service cannot
provide measurements and produces FAIL, rather than opening a second reader.

Output includes one-second arrival rates, jitter distribution, largest gap and
burst, metadata and its arrival relationship, raw-clock play-time cross-checks,
and P count/p50/p95/max. A successful run ends with
`PASS: steady real-time pacing within 20 ms`; failed or insufficient observations
exit non-zero. The summary also fails if a pacing fault occurred after steady
delivery was established, even if delivery later recovered. Jitter distribution
logs include warm-up, which is labelled separately from the steady-state check.
JSON lines preserve events for subsequent inspection. The probe
checks local pacing, not audible alignment or physical lamp latency.

The Light timing card uses the existing two-second status refresh. Its AirPlay
Details shows M, P, fine-tune and applied delay. Auto is
available for AirPlay's virtual-player latency entry. Fixed, paused, measuring
and unavailable states retain words and icons as well as colour.

The existing 30 Hz scene output quantises the requested wait to a scene interval
(about 33 ms). Measurement precision describes P, not absolute audible or lamp
alignment. No physical installation was accessed during development.

## LMS head start and generalised timed scheduling

The timestamped output path now accepts either the AirPlay early tap or an LMS
SHM write-clock estimate. The PCM producer and DSP are unchanged. In LMS sync-group
mode, the virtual player's verified `playDelay` advances it relative to the real
speaker. `startDelay` is only read: a non-zero value warns because start and
steady-state offsets would differ. Manual follow mode and head start 0 retain the
previous delay-buffer path.

The one production SHM reader observes the v1 absolute stereo-frame write position,
generation and gap counter with monotonic read timestamps on every poll. The
canonical worker's existing 5 ms wait targets 200 Hz when waiting for data; late
reads are rejected, rather than interpreted as producer skips. There is no second
PCM reader. A 30-second sliding fit constrains advancing positions between their
previous and first-observing reads. Long-baseline midpoint slopes estimate rate,
limited to ±2000 ppm around the reported nominal rate; robust 95th-percentile lower
and 5th-percentile upper interval bounds estimate the clock offset. At startup it
uses nominal rate. Its accuracy depends on having varied, timely read brackets;
simulated paced writers with jitter and drift are tested to p95 error ≤2 ms.

Audible time is fitted write time + configured head start + speaker output delay.
Canonicalisation preserves this through existing play spans; fine-tune is applied
once by SceneSchedule. Every publication is rendered and scheduled, including
onsets between output ticks. The 30 Hz sender displays the newest due scene, as
with AirPlay. A past target is sent on the next output tick, never held further.
Negative trim is limited by measured lead p5 minus median processing.

A source generation/gap change, a predicted write outside its read bracket by more
than 5 ms, a pause beyond the observed export-batch interval plus 5 ms (at least
20 ms), transport pause/resume, track change or a backwards transport seek starts
a new timing epoch.
The triggering PCM is discarded and queued scenes from the old epoch cannot be
sent. A poll gap over 15 ms does not prove a skip and is excluded from the fit.
The Hue ownership and release generations continue to invalidate scheduled scenes.

When lead p5 stays below p95 processing +40 ms for five continuous seconds, output
uses the existing delay-buffer path and reports “Not enough head start, using delay
instead”. Measurements continue through that path. Scheduling returns automatically
when measured lead reaches that threshold; its generation changes to discard old
queued work. No receiver or player restart is used for fallback or recovery.
See the LMS head-start procedure in configuration.md for owner calibration.

### LMS registration, group readiness and write-clock status

Press Go before synchronising in LMS: yeney-player normally registers only while
its coupling is active. Head start is applied in a cancellable background task,
not during the first SHM availability check. Scheduling requires verified
`playDelay` and an external speaker reported by the existing sync-group observer.
The existing observer refreshes every five seconds and reacts to sync/client
notifications; no second group poller is introduced. It invalidates timing when
the group changes or the player reconnects. Group changes invalidate scheduling
before speaker reconciliation, and a verification superseded by a later group
refresh cannot enable scheduling. Registration failures continue to
retry after the initial 30-second readiness window; preference failures use
1/2/5/10/30-second backoff. Stop cancels CLI I/O and closes the owned socket.
LMS normally restores group membership on reconnect. If the card says
“Not synced with a speaker yet: sync it in LMS”, restore membership in LMS.

Every scheduled LMS publication records its receipt and scene-ready timestamps.
Receipt is captured at the start of the SHM reader poll, so processing includes
clock fitting and PCM capture as well as analysis and rendering.
Actual output sends complete receipt/ready/send provenance. Processing excludes
scheduled queue residence and includes the send call. The scheduler generation
is authoritative for LMS receipt eligibility, rather than AirPlay's metadata
cadence boundary. Unknown processing is shown as unknown, not 0 ms; sub-millisecond
measurements retain a decimal digit. The existing headroom safety rule uses this
measured processing time.

The scheduled card's steadiness is the p95 distance of fitted write times outside
their read-time intervals, in milliseconds. Measurement count is the number of
accepted intervals in the current 30-second fit; the existing sparkline shows the
last seven residuals. These are clock-fit observations, not position-probe samples.
The card names the observed speaker and retains its existing layout. A zero
interval residual means the fit stays within its read brackets; it does not
claim zero absolute clock error or zero physical lamp latency.
