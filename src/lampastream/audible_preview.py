"""Preview-only playback timeline; never changes output scenes or scheduling."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, replace

from .accent import AccentLayer
from .onset_envelope import TriggerEnvelope

BANDS = ("all", "bass", "mid", "treble")


@dataclass
class PreviewScene:
    scene: object
    features: object
    render_time: float
    accent_value: float
    lifts: list
    playback_shift: float
    baseline: object
    positions: tuple
    profile: object

    def __getattr__(self, name):
        return getattr(self.scene, name)

    def color_at(self, position, t):
        return self.scene.color_at(position, t)


def render_metadata(scene):
    """Find metadata through precision and offline provenance wrappers."""
    while scene is not None:
        if isinstance(scene, PreviewScene):
            return scene
        scene = getattr(scene, '__dict__', {}).get('scene')
    return None


class AudiblePreview:
    def __init__(self, hold, release, policy, publish=None):
        self.envelopes = {band: TriggerEnvelope(hold, release) for band in BANDS}
        self.publish = publish
        self.pushed = set()
        self.policy = policy
        self.events = {}
        self.seen = set()
        self.until = dict.fromkeys(BANDS, -float('inf'))
        self.pending = []
        self.sequence = 0
        self.timestamped = False
        self.colours = []
        self.metadata = None
        self.lifts = []
        self.sent_time = None
        self.count = 0
        self.current_events = ()
        self.latest_audible = None
        self.accent = AccentLayer()

    def reset(self):
        if self.publish is not None:
            self.publish(dict(type='preview_reset'))
        envelope = self.envelopes['all']
        self.__init__(envelope.hold_s, envelope.release_s, self.policy, self.publish)

    def route(self, timestamped):
        if timestamped != self.timestamped:
            self.reset()
            self.timestamped = timestamped

    def register(self, event, lamp_time, timestamped):
        self.route(timestamped)
        if event.id in self.events:
            return
        stamp = event.play_monotonic if timestamped else lamp_time
        if stamp is None:
            return
        self.events[event.id] = (event, stamp)
        if timestamped:
            for band in event.bands | {'all'}:
                self.envelopes[band].trigger(event.strength, stamp, self.policy)
        if len(self.events) > 1000:
            oldest = next(iter(self.events))
            self.events.pop(oldest)
            self.seen.discard(oldest)
            self.pushed.discard(oldest)

    def push(self, metadata, stamp, colours, timestamped):
        """Publish once, independently of reads and the 20 Hz continuous socket."""
        due = [(event, audible if timestamped else stamp)
               for identity, (event, audible) in self.events.items()
               if identity not in self.pushed and
               (audible <= metadata.render_time + metadata.playback_shift + 1e-9
                if timestamped else audible <= metadata.render_time)]
        if not due:
            return
        if callable(colours):
            colours = colours()
        due.sort(key=lambda item: item[1])
        while due:
            anchor = due[0][1]
            group = [item for item in due if item[1] - anchor <= .005]
            due = due[len(group):]
            self.pushed.update(event.id for event, _ in group)
            # Keep individual timestamps inside a coalesced transport message:
            # browser activation must never pull a later event forward.
            events = []
            for event, audible in group:
                peaks = {band: min(1., max(0., event.strength))
                         if band in event.bands | {'all'} else 0. for band in BANDS}
                events.append(dict(id=event.id, audible_monotonic=audible,
                                   peaks=peaks, bands=sorted(event.bands)))
            channels = [dict(zip(('r', 'g', 'b'), c.to_16bit(), strict=True))
                        for c in colours]
            for event in events:
                event.update(channel_colours=channels, channel_accent_lifts=list(metadata.lifts),
                             accent_value=metadata.accent_value)
            envelope = self.envelopes['all']
            payload = dict(type='event', audible_monotonic=anchor, events=events,
                           event_count=len(events), bands=sorted(set().union(
                               *(event.bands for event, _ in group))),
                           hold_s=envelope.hold_s, release_s=envelope.release_s,
                           policy=self.policy, channel_colours=channels,
                           channel_accent_lifts=list(metadata.lifts),
                           accent_value=metadata.accent_value)
            if self.publish is not None:
                self.publish(payload)

    def sent(self, scene, stamp, colours, timestamped):
        metadata = render_metadata(scene)
        if metadata is None:
            return
        self.route(timestamped)
        self.sequence += 1
        self.count = 0
        self.current_events = ()
        # Retain the exact post-boundary samples. Only their preview presentation
        # moves from the lamp event clock onto the event playback clock.
        audible = stamp + metadata.playback_shift if timestamped else stamp
        lifts = []
        for position, colour in zip(metadata.positions, colours, strict=False):
            before = metadata.baseline.color_at(position, stamp)
            lifts.append(max(0., colour.r-before.r, colour.g-before.g, colour.b-before.b))
        heapq.heappush(self.pending, (audible, self.sequence, metadata, tuple(colours), lifts))
        if not timestamped:
            self.push(replace(metadata, lifts=lifts), stamp, colours, False)
        self.snapshot(stamp)

    def snapshot(self, now):
        while self.pending and self.pending[0][0] <= now:
            self.sent_time, _, self.metadata, self.colours, self.lifts = heapq.heappop(self.pending)
        limit = now if self.timestamped else (
            self.metadata.render_time if self.metadata is not None else -float('inf'))
        due = [(event, stamp) for identity, (event, stamp) in self.events.items()
               if identity not in self.seen and stamp <= limit]
        for event, stamp in due:
            self.seen.add(event.id)
            audible = stamp if self.timestamped else self.sent_time
            self.latest_audible = audible
            for band in event.bands | {'all'}:
                self.until[band] = audible + .05
        if due:
            self.count += len(due)
            self.current_events = tuple(event for event, _ in due)
        features = self.metadata.features if self.metadata else None
        values = {band: (self.envelopes[band].value(now) if self.timestamped else
                  getattr(features, 'onset_envelope' + ('' if band == 'all' else '_'+band), 0.))
                  for band in BANDS}
        active = {band: now <= self.until[band] for band in BANDS}
        newest = self.latest_audible
        accent_value = self.metadata.accent_value if self.metadata else 0.
        if self.timestamped and features is not None:
            audible_events = [(event, stamp) for event, stamp in self.events.values()
                              if stamp <= now]
            latest = max(audible_events, key=lambda item: item[1])[0] if audible_events else None
            view = replace(features, onset_events=(latest,) if latest else (),
                           onset_strength=latest.strength if latest else 0.,
                           onset_count_since_render=0,
                           **{'onset_envelope'+('' if band == 'all' else '_'+band): values[band]
                              for band in BANDS})
            self.accent.render(self.metadata.baseline, view, self.metadata.profile)
            accent_value = self.accent.last_value
        return {
            'audible_monotonic': now if self.timestamped else self.sent_time,
            'colours': self.colours,
            'onset': active['all'], 'pcm_onset': active['all'],
            **{'onset_'+band: active[band] for band in BANDS[1:]},
            **{'onset_envelope'+('' if band == 'all' else '_'+band): values[band]
               for band in BANDS},
            'onset_count_since_render': self.count,
            'onset_events': self.current_events,
            'onset_age_s': now-newest if newest is not None else None,
            'accent_value': accent_value,
            'channel_accent_lifts': self.lifts,
        }


def coalesce_messages(messages):
    """Merge already available socket bursts without delaying normal-route sends."""
    result = []
    for message in messages:
        previous = result[-1] if result else None
        if (previous is not None and previous['type'] == message['type'] == 'event'
                and 0 <= message['audible_monotonic'] - previous['audible_monotonic'] <= .005
                and all(previous[key] == message[key]
                        for key in ('hold_s', 'release_s', 'policy'))):
            result[-1] = dict(previous, events=previous['events'] + message['events'],
                              event_count=previous['event_count'] + message['event_count'],
                              bands=sorted(set(previous['bands']) | set(message['bands'])))
        else:
            result.append(message)
    return result
