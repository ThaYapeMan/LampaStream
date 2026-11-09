# Whole-file library grid

The source-independent `grid.analyser.analyse(bytes)` decodes mono at native
rate, runs librosa 0.11.0 (`start_bpm=120`, `tightness=100`), refines tempo,
scores half/double candidates within 60–180 BPM against low-band attack energy
and its autocorrelation, and shifts phase by the median attack offset.
A 512-sample beat hop with `trim=False` retains positions through quiet sections
and the file tail. Rigid tracks use a robust inlier slope fit to score rhythmic regularity. Tempo
is the whole-file median attack-refined inter-beat interval; beat positions retain
librosa's local timing before the median phase correction. Ties choose the slower tempo.
JSON contains version, SHA-256, duration, rate, tempo, beats, kick flags,
break/drop sections, confidence and timing basis. FLAC/PCM use soundfile;
ALAC in M4A uses FFmpeg when libsndfile rejects the container. MP3 timing is
unknown and does not enable the production prior.

`LmsGridAdapter` alone resolves track IDs to `/music/<id>/download`. The existing
metadata subscription adds `uf`; once per changed track it reads the next
playlist entry with `status <index+1> 1 tags:uf`. It does not poll additional
status/time queries. One asynchronous worker fetches current then next track,
verifies filesize, and launches a low-priority, time-bounded analysis subprocess.
Downloads never use `/stream`. The existing virtual player's `lms_host` and
`lms_port` (HTTP port, normally 9000) define the HTTP base. No library mount is required.

`GridCache` stores `/var/lib/lampastream/grids/<sha256>.json` with bounded LRU
aliases for `lms:<id>:<filesize>` (default 2000 grids and aliases). After download,
existing content hashes reuse analysis even across library IDs. Writes replace
JSON atomically. Acquisition failures log and retain live analysis.

The strict lossless source publishes an optional generic `content_position_s`
coordinate. Canonicalization resamples that coordinate independently of room
play time. The LMS adapter supplies a generic prior `(identity, grid, origin,
metadata)` to BeatFusion. After this boundary nothing knows LMS. Onset detection
and the live tempo clock continue running. Grid beats produce existing
ProcessorUpdates and OnsetEvents, pass through existing AudioFeatures and the
same audible clock, scheduler, Effects, Scenes and output driver. Grid beats
without kicks emit nothing; drops have strength 1, ordinary beats .8. The whole
track's section data supplies `time_to_next_drop_s` without scheduling a separate
output path. Beat events enter the existing scheduler 100 ms ahead; their processor
contribution still describes the observed hop, preserving publication freshness.
Beat-source transitions use the existing scheduler generation fence. Onset and Off ignore the prior. AirPlay supplies no prior.

While loud, fewer than half of the previous eight seconds' kick beats confirmed
within 70 ms drops the prior for that track identity. The warmed live tracker
continues immediately. A new identity clears rejection. Exact source content
position is required; metadata position estimates never enable a grid.

The preview, status and capture manifest expose `beat_source`, `grid_confidence`,
`grid_tempo`, `grid_cache`, `grid_fetch_state`, and `grid_dropped_reason`.
Now Playing uses “grid” in the existing tempo label and exposes confidence and
rejection in Light timing Details. No persisted schema version changes.
