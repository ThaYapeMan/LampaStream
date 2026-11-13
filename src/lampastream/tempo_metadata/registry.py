"""Static provider definitions, following the engine/output registry pattern."""
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    key: str
    artist: str = ''
    title: str = ''
    duration: float | None = None
    isrc: str = ''
    external_id: str = ''
    fingerprint: dict | None = None
    tags: dict | None = None
    correction: dict | None = None


@dataclass(frozen=True)
class LookupResult:
    fields: dict
    raw_payload: dict
    confidence: float
    status: str = 'ready'


class Provider(Protocol):
    def lookup(self, identity: Identity) -> LookupResult: ...


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    module: str
    capabilities: tuple[str, ...]
    lookup_keys: tuple[str, ...]
    rate_limit: float
    ttl: float
    redistributable: bool
    requires_credentials: bool
    enabled: bool
    status: str = 'active'
    priority: int = 0
    leaves_lan: bool = False
    always_enabled: bool = False
    test_only: bool = False
    manual: bool = False
    display_label: str = ''

    def make(self, **options):
        return import_module(self.module).Adapter(**options)


PROVIDERS = {
    spec.name: spec for spec in (
        ProviderSpec('owner', 'lampastream.tempo_metadata.owner',
                     ('tempo', 'phase_offset_s'), ('fingerprint',), 0., 0., True, False, True,
                     priority=1000, always_enabled=True, manual=True),
        ProviderSpec('local-tags', 'lampastream.tempo_metadata.local_tags',
                     ('tempo',), ('fingerprint', 'external_id', 'artist+title'),
                     0., 86400., True, False, True,
                     priority=100, always_enabled=True),
        ProviderSpec('recorded-fixture', 'lampastream.tempo_metadata.recorded_fixture',
                     ('tempo',), ('artist+title', 'ISRC', 'external_id', 'fingerprint'),
                     0., 3600., False, False, False, priority=10, test_only=True),
        ProviderSpec('songbpm', 'lampastream.tempo_metadata.songbpm',
                     ('tempo',), ('artist+title',), 1., 86400., False, False, False,
                     priority=50, leaves_lan=True, display_label='SongBPM'),
        ProviderSpec('beatport', 'lampastream.tempo_metadata.beatport',
                     ('tempo', 'key', 'genre'), ('artist+title',), 1., 86400.,
                     False, False, False, priority=75, leaves_lan=True,
                     display_label='Beatport'),
    )
}
