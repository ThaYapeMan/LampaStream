"""Non-mutating offline observers of current picker and schedule decisions."""
from __future__ import annotations

from lampastream.airplay_early import SceneSchedule


class PickerObserver:
    """Keep candidate raw flux beside current flux; do not alter picker returns."""

    def __init__(self, beat):
        self.rows = {}
        self.position = 0
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
            return feed(frame)

        beat.feed = observed

    def attach(self, band, picker):
        original = picker.process_odf_event

        def observed(flux, level_dbfs=None):
            event = original(flux, level_dbfs)
            if event is not None:
                candidate = self.position + (3 - event.availability_frame
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


class ScheduleObserver(SceneSchedule):
    """Observe overflow/coalescing while calling the unchanged scheduler methods."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.coalesced = set()
        self.overflow = set()

    def add(self, scene, *args, **kwargs):
        previous = {item[2].scene_id for item in self.queue} | {scene.scene_id}
        super().add(scene, *args, **kwargs)
        self.overflow.update(previous - {item[2].scene_id for item in self.queue})

    def due(self, now, generation):
        candidates = {item[2].scene_id for item in self.queue if item[0] <= now}
        result = super().due(now, generation)
        if result is not None:
            self.coalesced.update(candidates - {result[0].scene_id})
        return result
