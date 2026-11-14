# LAT-02 field evidence

Capture `ab-20261110-2338` used LampaStream `a274ddd` with Mau P’s “Just A Little
Bit More (Extended)” on the LMS route. The Tracker coupling used a cached
library grid from 6.8 s at 127.95 BPM and 0.89 confidence. Auto latency followed a
Sonos Port (`48:a6:b8:20:39:64`) with `measurement_basis=lms-content-v1`.

Grid accents against the offline reference yielded the following offsets.

| Bin (s) | Median (ms) | MAD (ms) | n |
|---|---|---|---|
| 0–30 | +6 | 15 | 70 |
| 30–60 | 0 | 10 | 63 |
| 60–90 | −14 | 8 | 54 |
| 90–120 | −31 | 7 | 64 |
| 120–150 | −38 | 7 | 62 |
| 150–180 | −53 | 8 | 64 |
| 180–210 | −45 | 7 | 51 |
| 210–240 | −44 | 9 | 59 |
| 240–286 | no accents (kickless breakdown, by design) | | |
| 286–300 | +12 | 17 | 29 |
| 300–330 | +34 | 14 | 64 |
| 330–360 | +42 | 15 | 64 |
| 360–390 | +67 | 15 | 21 |

Jitter (MAD 5–15 ms) is in the class GRID-01 proved offline. The **median slides** and **steps +66 ms**
across the breakdown. Only 89 of 790 reference beats are hit within ±10 ms; 387 within ±40 ms.

The probe reported the following values in `lms-status.jsonl` under `light_timing.status`.

| t (s) | applied_delay_ms | median_residual_ms | state |
|---|---|---|---|
| 14 | −63 | −62 | stable (startup step used) |
| 56 | −45 | −51 | stable |
| 101 | −24 | −44 | stable |
| 147 | +2 | −23 | stable |
| 192 | +29 | +5 | stable |
| 238 | +53 | +28 | stable |
| 284 | +80 | +51 | stable |
| 330 | +104 | +77 | stable |
| 376 | +129 | +103 | stable |

The grid’s median offset slid during playback and stepped by 66 ms across the
breakdown. Of 790 reference beats, 89 matched within ±10 ms and 387 within ±40 ms.

After the startup step, the probe recomputed the session offset from each new
consensus, projected it with a drift estimate bounded to ±1 ms/s and set a new
target. The applied delay slewed toward that target at up to 5 ms/s. The target
continued moving while the grid had no accents to render, so resumed accents
inherited the changed delay.

The position-pair residual rose by 0.46 ms/s, consistent with the 2026-11-04
clock-rate probe’s 0.455 ms/s. The Port’s LMS position is derived from integer
UPnP `RelTime` and re-anchored on every poll. CLOCK-00 measured agreement among
producer, arrival, content, stamp and pipeline clocks within ±0.2 ppm. The native
content clock supplies the playback rate. The followed player’s position sets
the session anchor and guards for discrete jumps. The grid already schedules
accents on the content clock.

The track display’s `position_s` slid −0.16 ms/s against wall time in the same
capture. That display coordinate retains its existing behavior.

## Field confirmation 2026-11-11

Two captures of `21b3d18`, at 09:44 and 18:34, used Mau P, the LMS coupling
in Tracker mode and the active library grid.

LAT-02 did what it was meant to do: `applied_delay_ms` was **constant for the whole track** in both runs
(−115.0 ms from the startup step at 13 s to the end; −149.2 ms in the evening run), `guard_residual_ms`
reported, no re-anchor. 640 grid accents per run, MAD 6–10 ms per 30 s bin.

But the capture's own per-bin table still shows a slide — now −0.58 ms/s, −215 ms over the track, in
both runs, with the applied delay flat. So the slide is not in the lights. It is in the **coordinate the
logger uses**:

- `*-beats.csv` `audible_t` comes from `PlayerManager.track_time_at()`, which maps the event's room
  monotonic time through `TrackPosition.position_s/observed_at` of the **followed player's LMS status
  subscription** (`LmsTrackPositionSource._set_snapshot`, 5 ms/s bounded corrections). For a Sonos Port
  that position is the UPnP `RelTime` integer-second re-anchor; in both captures it ran at
  **−0.549 / −0.519 ms/s against wall time** (814 / 826 status rows).
- Re-mapping the same grid events with **one anchor and slope 1** (first status position after 15 s plus
  wall-clock elapsed) gives: residual slide **+0.018 ms/s** (both runs), every 30 s bin within
  **−2.6 … +10.8 ms** (morning) and **−1.3 … +8.7 ms** (evening) of the first bin, MAD 6–10 ms.
  The grid accents are steady; the yardstick moves.

Consequence: the LMS acceptance table in `analysis.md` cannot pass while it is drawn in the followed
player's `time ?` coordinate, whatever the lights do. The AirPlay route is unaffected (RTP anchor):
+10 … +14 ms constant, MAD 5 ms, in both runs.

Two constant facts the capture can *not* judge and must say so: the absolute offset of the LMS route
(+74 ms morning / +105 ms evening in the fixed-anchor coordinate) depends on the anchor chosen and on the
per-session `time ?` consensus (the two sessions differ by 34 ms in applied delay and 31 ms in offset —
the same quantised source). Absolute room alignment is OUT-01 (camera) and CLOCK-01 (YeneY ms play
points), not this ticket.


## Proven stream origins (LAT-05)

yeney-core `9d5aa42` establishes the origin before PCM enters canonical analysis.
FLAC supplies its decoded frame index, including after a seek. ALAC/M4A now uses
LMS's preserved `mdhd` duration minus the delivered `stts` duration, requiring
consistent complete tables and an exact whole-packet difference. Original trim
coordinates are intersected with the delivered range. An unprovable M4A origin
and MP3 remain unknown. LampaStream consumes the core's known bit without
file-type branches or sound comparison; unknown streams are never measured.

The old `9fba26f` core published `trimBegin` as a known origin for every M4A
response, commonly a false zero after LMS had sought. This explains the 112
field evidence: errors grew with the alignment seek, with 0.549, 0.744, 0.806
and 1.013 s seeks refused by the landing guard. With proven origins, the landing
error follows the real packet landing rather than the whole seek.
LMS may land more than one packet before the request: the real LMS 9.1.1
0.744 s seek delivered frame 28,672 at 44.1 kHz (0.650158730 s), 93.841 ms
early. The reference PCM must match at the reported origin; distance from the
request is informational. Silent or repeated PCM earlier in a track does not
change the delivered block's coordinate.

AIFF/WAV remains a known limitation: the core's `PcmWorker` calls
`setSourceStart(0)` even after a seek. The unchanged 0.5 s landing guard remains
its protection, pending a separate core fix. No adapter guesses an origin.

Saved `lms-content-v1` room calibrations from M4A can contain the false origin.
The new `measurement_basis=lms-content-v2` invalidates saved v1 starting values
and measures afresh for all files, since saved rows do not record the file type.
Room/session/trim arithmetic and the once-per-session startup step are unchanged.

The SHM player does not request the core's optional sample-rate conversion
(`Sink::conversionRate()` defaults to zero). LampaStream performs canonical
resampling itself. Other core hosts enabling conversion receive output-frame
origins only for divisible landings with zero gapless phase. Consumers needing
from-start-identical PCM must skip the settling frames; YNPT does not carry that
internal callback's settling bound.

While playing without a session anchor the probe logs every ten seconds:
`latency probe waiting: reason=… track=… seek_s=… since_s=…`.
The first caught probe exception per play also logs its text at WARNING.
Unknown origins say `Stream origin unknown for this file`; excessive landings
say `Seek landing >500 ms: ambiguous absolute content origin`. Missing or stale
clocks retain `No fresh absolute PCM content clock`. After fifteen seconds the
reason appears through the existing `latency_warning` display and clears when
anchored. Every `latency basis` is followed by a `latency sample` outcome:
accepted, rejected, or held as a step candidate.

`/api/status` exposes `session_anchor_set`, `current_play` and
`applied_delay_play`; `/api/player-latencies` exposes them in each active probe's
`status`. Play identifiers are follower transition numbers, so seek and
pause/resume transitions distinguish sessions even for the same track. Before
a new anchor, `applied_delay_play` still identifies the earlier mapping (or is
null at service start); no timing arithmetic or layout changes are implied.
