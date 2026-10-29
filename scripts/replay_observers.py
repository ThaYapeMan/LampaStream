"""Non-mutating offline observers of current picker and schedule decisions."""
from __future__ import annotations

from lampastream.scheduler import Scheduler


class PickerObserver:
    """Keep candidate raw flux beside current flux; do not alter picker returns."""

    def __init__(self, beat):
        self.rows = {}
        self.position = 0
        self.positions = {}
        pipeline = beat._state.onset_pipeline
        if hasattr(pipeline, "_onset"):
            pickers = {"all": pipeline._onset}
        elif hasattr(pipeline._detector, "_picker"):
            pickers = {"all": pipeline._detector._picker}
        else:
            detector = pipeline._detector
            pickers = {band: getattr(detector, f"_{band}_det")
                       for band in ("bass", "mid", "treble")}
        for band, picker in pickers.items():
            self.attach(band, picker)
        feed = beat.feed

        def observed(frame):
            if len(frame.hop_sample_starts) > 1:
                raise ValueError("Picker observer requires canonical chunks of at most one hop")
            if frame.hop_sample_starts:
                self.position = frame.hop_sample_starts[0]
            self.positions = {band: (self.position, 3)
                              for band in ("all", "bass", "mid", "treble")}
            if frame.mag_frames_short is not None and frame.hop_sample_starts_short:
                for band in ("all", "mid", "treble"):
                    self.positions[band] = frame.hop_sample_starts_short[0], 0
            return feed(frame)

        beat.feed = observed

    def attach(self, band, picker):
        original = picker.process_odf_event

        def observed(flux, level_dbfs=None):
            event = original(flux, level_dbfs)
            if event is not None:
                start, attack = self.positions.get(band, (self.position, 3))
                candidate = start + (attack - event.availability_frame
                                     + event.candidate_frame) * 480
                self.rows[candidate, band] = {
                    "candidate_sample": candidate,
                    "candidate_strength": event.candidate_strength,
                    "reported_sample": candidate,
                    "reported_strength": event.candidate_strength,
                    "decision_sample": candidate + picker.lookahead_frames * 480}
            return event

        picker.process_odf_event = observed

    def at(self, position, band):
        row = self.rows.get((position, band))
        if row is None and band == "all":
            candidates = [self.rows[position, b] for b in ("bass", "mid", "treble")
                          if (position, b) in self.rows]
            # Match the existing multiband aggregate's maximum CURRENT strength.
            row = max(candidates, key=lambda r: r["reported_strength"]) if candidates else None
        return row or {}


class ScheduleObserver(Scheduler):
    """Observe overflow/coalescing while calling the unchanged scheduler methods."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.coalesced = set()
        self.overflow = set()

    def add(self, *args, **kwargs):
        previous = {entry.sequence for entry in self.queue}
        super().add(*args, **kwargs)
        self.overflow.update((previous | {self.sequence})-
                             {entry.sequence for entry in self.queue})

    def due(self, now):
        candidates = [entry for entry in self.queue if entry.deadline <= now+1e-10]
        result = super().due(now)
        if result is not None:
            selected = next(entry.sequence for entry in candidates if entry.request is result)
            self.coalesced.update({entry.sequence for entry in candidates}-{selected})
        return result
