# Timestamp references for A/B captures

`mau-p-jalbm/beats.csv` and `summary.json` are the owner's supplied offline
analysis kit for Mau P, “Just A Little Bit More (Extended)”, LMS track 44436.
They contain timestamps/statistics only, no audio. The archived `beats-librosa.csv` lists librosa beats; `beats.csv` now holds
the owner-authorised rigid timestamps and owner-verified bass drum labels (see the folder README);
the summary separately identifies the first bass drum (0.499 s) and first beat
(0.476 s). Its fitted steady tempo is 127.9984 BPM.

`airplay-82181c5.csv` pins 67 non-predicted detections produced on the real
WebSocket event path with the clock, AirPlay metadata source and logger loaded
from `82181c5`. Synthesis: 48 kHz stereo; 32 seconds; bass drums from 0.5 s every
60/128 s; 100 ms 60 Hz sine bursts, amplitude 0.9, exponential decay 55/s.
The track-zero playback anchor is 1.5 s; replay uses the committed default config.
The current production producer/logger must match these track seconds within 2 ms.
There is no audio in this pin either. CI reads the numeric pin, so shallow
checkouts do not need historical commits. Explicit regeneration requires history:

```bash
LAT03_GENERATE_AIRPLAY_PIN=1 .venv/bin/python -m pytest -n 0 -s \
  tests/test_airplay_mapping_pin.py::test_airplay_actual_socket_detection_track_time_matches_82181c5
```

Baseline source SHA-256:

- `src/lampastream/audible_clock.py`: `c1e51e2419d1ff4b6718ce5057fc3c578efc7301108a977e1a0e39f36bbe90e7`
- `src/lampastream/track_position.py`: `78d4890c9a9213a0cddb7773a65b4615365ecddc32310cad7d89147700c16981`

`avh-udkm/beats.csv` contains the owner's 1053 rigid 129.985 BPM timestamps and
bass drum flags for Armand Van Helden, “U Don't Know Me feat. Duane Harden (Original
Mix)”. See that folder's README for provenance and private fixture variables.

## Owner-verified disputed spots — 2026-11-12

Disputed reference labels are owner-verified by listening from this date onward.
The changes below follow the owner's verdicts and explicit ranges; labels are
not regenerated from analyser output. Timestamps/statistics only, no audio.

| Track | Reviewed spot | Owner verdict (2026-11-12) | Reference consequence |
| --- | --- | --- | --- |
| UDKM | 0:10–0:28 | Bass drum present, double hit | Presence is 1 throughout the owner-authorized 0.4–28.5 s range |
| UDKM | 0:39–0:52 | Bass drum present, single/double | Presence is 1; the former short stops are removed |
| UDKM | 7:58–8:06 | Bass drum continues to the end | Presence is 1 from the old 480.9 s row through the end |
| Mau P | 1:25.3 and 2:29.5 | Soft bass drum present | Rows 182 and 319 become 1 |
| Mau P | 3:08.9, 3:09.4, 3:09.9, 3:14.5, 6:10.8, 6:17.4 | Softer beat: flash with less intensity | Rows 403, 404, 405, 415, 791, 805 become 2 (reduced) |
| Lou Rawls | 1:32.5 and 1:48.1 | Band continues in time with a solid bass drum | Misplaced tracker beats, not missing beats; re-place locally without changing the count |

Mau P uses `kick` = 0 (absent), 1 (full bass drum), or 2 (reduced accent).
The exact authorized edits total **653 full, 155 absent and 6 reduced**, 814
rows. Reference-2 rows are excluded from binary scoring until BEAT-02 supplies
reduced intensity; the current Boolean grid output on them is informational.

UDKM's current timestamps use the first layered transient at 129.985 BPM.
`avh-udkm/beats-body-phase.csv` archives the previous body-phase file, including
its historical unreviewed labels; it is not the current label authority.
Current UDKM flag agreement gates on the body at t ≥60 s. Soft bass drums in
quiet intros are a documented conservative gap, with per-channel evidence in
[the findings](../../../docs/research/grid01-udkm-findings.md) and the 5d report.
