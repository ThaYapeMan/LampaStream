# Armand Van Helden — U Don't Know Me (Original Mix)

Owner-supplied timestamps, 2026-11-11; no audio. `beats.csv` preserves the
1053 rows of the supplied `beats.csv.csv` byte for byte. Columns are zero-based
`beat`, track-content `time_s`, and binary `kick`. The rigid grid is 129.985 BPM.
The supplied flags include isolated one- and three-beat gaps; acceptance permits
at most 2% flag disagreement while requiring output runs of at least four beats.

Private ALAC audio is opt-in through `LAMPASTREAM_GRID_FIXTURE_UDKM`; it must
remain outside the checkout and CI. Lou Rawls uses
`LAMPASTREAM_GRID_FIXTURE_LOU` (the fixture is ALAC `.m4a`, not `.flac`). Mau P
retains `LAMPASTREAM_GRID_FIXTURE`. All acquisition tests use loopback fake LMS.
