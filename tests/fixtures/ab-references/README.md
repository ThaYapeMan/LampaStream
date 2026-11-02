# Timestamp references for A/B captures

`mau-p-jalbm/beats.csv` and `summary.json` are the owner's supplied offline
analysis kit for Mau P, “Just A Little Bit More (Extended)”, LMS track 44436.
They contain timestamps/statistics only, no audio. The CSV lists librosa beats;
the summary separately identifies the first kick (0.499 s) and first beat
(0.476 s). Its fitted steady tempo is 127.9984 BPM.

`airplay-82181c5.csv` pins 67 non-predicted detections produced on the real
WebSocket event path with the clock, AirPlay metadata source and logger loaded
from `82181c5`. Synthesis: 48 kHz stereo; 32 seconds; kicks from 0.5 s every
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
