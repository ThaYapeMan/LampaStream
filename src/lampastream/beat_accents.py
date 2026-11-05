"""Select the lighting event stream without changing analysis or audible clocks."""
from dataclasses import replace


def gain_progress(gain, ceiling):
    """Zero through 8x; linear to one at the configured ceiling."""
    if gain <= 8:
        return 0.
    return min(1., (gain-8)/max(ceiling-8, 1e-9))


def onset_strength_floor(gain, ceiling, floor):
    """Extra raw-flux floor; normalized confidence can saturate even on quiet input."""
    gain = min(gain, ceiling)
    return floor*gain*gain_progress(gain, ceiling)


def select_events(mode, tracker_events, records, ceiling=64., floor=.3):
    if mode == "off":
        return []
    if mode == "tracker":
        return list(tracker_events)
    if mode != "onset":
        raise ValueError("Invalid beat_accent_mode")
    events = []
    for record in records:
        features = record.features
        minimum = onset_strength_floor(features.agc_gain, ceiling, floor)
        for event in features.diagnostic_events:
            if event.predicted or event.strength_raw < minimum:
                continue
            # Diagnostic events retain detector sample identities. Attach the
            # publication's existing clock anchor just as the fused stream does.
            offset = (event.candidate_sample-record.sample_pos)/48000
            events.append(replace(event, kind="beat", on_beat=False,
                received_monotonic=(features.received_monotonic+offset
                                    if features.received_monotonic is not None else None),
                play_monotonic=(features.play_monotonic+offset
                                if features.play_monotonic is not None else None)))
    return events
