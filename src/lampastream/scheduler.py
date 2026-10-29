"""One capability-driven scheduler for immutable render requests and sent scenes."""
from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RenderRequest:
    features: object
    sample: int
    audible: float
    lead: float = 0.
    events: tuple = ()
    render_time: float = 0.
    received_at: float = 0.
    source_sequence: int | None = None


@dataclass(order=True)
class Entry:
    deadline: float
    sequence: int
    request: RenderRequest = field(compare=False)


@dataclass
class SentEntry:
    scene: object
    features: object
    audible: float
    lead: float
    ready: float
    events: tuple
    cadence: bool


class Scheduler:
    """Advance rendering at exact deadlines, then coalesce inside the send ceiling.

    Event identities and the strongest unsent envelopes survive both coalescing
    stages. Renderer state advances only in monotonic deadline order. Precision
    samples and preview metadata travel with the same sent entry.
    """

    def __init__(self, capabilities, *, interval=1/30, origin=0., capacity=None):
        self.capabilities = capabilities
        self.interval, self.origin = interval, origin
        self.capacity = 1000 if capacity is None else capacity
        self.adaptive_capacity = capacity is None
        self._quiet_slots = {}
        self.coalesced_continuous = 0
        self.queue = []
        self.sequence = 0
        self.generation = None
        self.pending = None
        self.features = deque(maxlen=1000)
        self.blocked_until = -math.inf

    def clear(self):
        self.queue.clear()
        self._quiet_slots.clear()
        self.features.clear()
        self.pending = None

    def reset(self, generation):
        if generation != self.generation:
            self.clear()
            self.generation = generation

    def add(self, request, ready, *, cadence=False):
        self.sequence += 1
        if cadence:
            self.features.append(request)
        deadline = max(ready, request.audible-request.lead
                       - self.capabilities.transport_latency_s)
        if cadence and not (self.sequence == 1 and deadline <= ready+1e-10):
            slot = math.ceil((deadline-self.origin-1e-10)/self.interval)
            deadline = self.origin+slot*self.interval
        request.received_at = ready
        if self.adaptive_capacity:
            horizon_slots = math.ceil(max(0., deadline-ready)/self.interval)+2
            self.capacity = max(self.capacity, horizon_slots)
        if cadence and deadline in self._quiet_slots:
            previous = self._quiet_slots[deadline]
            previous.request = request
            previous.sequence = self.sequence
            self.coalesced_continuous += 1
            heapq.heapify(self.queue)
            return
        entry = Entry(deadline, self.sequence, request)
        heapq.heappush(self.queue, entry)
        if cadence:
            self._quiet_slots[deadline] = entry
        if len(self.queue) > self.capacity:
            # Continuous snapshots are replaceable. Events are never pruned:
            # ingress bounds their rate and accepted lookahead horizon.
            quiet = [entry for entry in self.queue if not entry.request.events]
            if quiet:
                removed = min(quiet)
                self.queue.remove(removed)
                if self._quiet_slots.get(removed.deadline) is removed:
                    self._quiet_slots.pop(removed.deadline)
                heapq.heapify(self.queue)

    def features_at(self, audible):
        return min(self.features, key=lambda request: abs(request.audible-audible), default=None)

    def next_due(self):
        return self.queue[0].deadline if self.queue else None

    def due(self, now):
        entries = []
        while self.queue and self.queue[0].deadline <= now+1e-10:
            entry = heapq.heappop(self.queue)
            if self._quiet_slots.get(entry.deadline) is entry:
                self._quiet_slots.pop(entry.deadline)
            entries.append(entry)
        if not entries:
            return None
        newest = entries[-1].request
        newest.render_time = entries[-1].deadline
        newest.events = tuple({e.id: e for entry in entries
                               for e in entry.request.events}.values())
        return newest

    def offer(self, request, scene, features, ready, cadence):
        from .audible_preview import render_metadata
        previous = self.pending.events if self.pending is not None else ()
        events = tuple({event.id: event for event in (*previous, *features.onset_events)}.values())
        metadata = render_metadata(scene)
        if metadata is not None:
            metadata.carried_events = events
        self.pending = SentEntry(scene, features, request.audible, request.lead,
                                 ready, events, cadence)

    def take(self, now, last_send, minimum_interval, *, reserve_until=None):
        self.blocked_until = last_send+minimum_interval
        if self.pending is None:
            return None
        if not self.pending.events:
            upcoming = [entry.deadline for entry in self.queue if entry.request.events
                        and now < entry.deadline < now+minimum_interval]
            if upcoming:
                self.blocked_until = max(self.blocked_until, min(upcoming))
            if reserve_until is not None:
                self.blocked_until = max(self.blocked_until, reserve_until)
        if now < self.blocked_until-1e-10:
            return None
        result, self.pending = self.pending, None
        return result
