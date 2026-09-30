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

## Delivery margin and processing

The managed margin **M is 500 ms**. Typical processing of 100–150 ms leaves
350–400 ms for local scheduling and transport variation. This is headroom, not
an assertion of a universally bounded worst case. Measured processing longer
than M triggers the fixed fallback because a delay cannot advance the lights.
The owner should validate each installation with the probe.

The installer and upgrade path atomically set these related general settings,
preserving unrelated operator settings and refusing ambiguous configurations:

```conf
audio_backend_latency_offset_in_seconds = -0.5;
audio_backend_buffer_desired_length_in_seconds = 0.0;
audio_backend_buffer_interpolation_threshold_in_seconds = 0.0;
```

Zero desired buffer is essential: leaving the default would deliver at M plus
one second. Zero interpolation threshold is compatible with that zero buffer.
The manifest records the margin and shairport revision; verification checks the
actual configuration too. Missing provenance or changed timing settings means
M is unknown and Auto uses the fixed fallback.

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
estimate in place indefinitely. The delay is
`max(0, M − median(P) + trim_ms)`. After the first steady value, each newly accepted
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
sparkline shows P, and Details shows M, P, fine-tune and applied delay. Auto is
available for AirPlay's virtual-player latency entry. Fixed, paused, measuring
and unavailable states retain words and icons as well as colour.

The existing 30 Hz scene output quantises the requested wait to a scene interval
(about 33 ms). Measurement precision describes P, not absolute audible or lamp
alignment. No physical installation was accessed during development.
