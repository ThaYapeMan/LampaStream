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
