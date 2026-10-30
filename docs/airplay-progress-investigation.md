# BATCH-01 AirPlay progress investigation

Architecture check: canonical PCM → one analyser → renderer/scheduler → outputs.
Progress acquisition remains in `track_position.py`; room-time mapping remains in
`audible_clock.py`. No player-specific downstream changes are justified.

The requested `25aedb4..8d886f7` range contains no changes to the metadata parser,
Shairport installer, socket delivery or TrackProgress component. The player-manager
changes select AudibleClock implementations and enable the native LMS play clock;
they do not change the AirPlay TrackPositionSource attachment or its delivery.
The existing simulated XML tests already cover prgr, RTP wrap, pause/resume,
seek, heartbeat and end; player clock invariant tests pass unchanged.

Consequently this inspection does **not** identify a first bad commit or establish
the field root cause. Naming ROUTE-01 as the cause would be unsupported. No
speculative production fix has been applied. To complete the investigation, capture
the single metadata reader's incoming `prgr`/metadata ordering on the affected
receiver (do not attach another FIFO reader), along with the delivered track
snapshot. This part remains open pending reproduction of the field sequence.
