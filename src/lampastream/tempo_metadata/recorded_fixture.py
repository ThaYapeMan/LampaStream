"""Test-only offline adapter. Production registry exposes it disabled."""
import json
from pathlib import Path

from .registry import LookupResult


class Adapter:
    def __init__(self, fixture=None):
        self.fixture = Path(fixture) if fixture else None

    def lookup(self, identity):
        if self.fixture is None:
            raise ValueError('Recorded fixture is available only in test harnesses')
        payload = json.loads(self.fixture.read_text())
        rows = [row for row in payload['tracks'] if row['key'] == identity.key]
        if len(rows) != 1:
            return LookupResult({}, {'matches': len(rows)}, 0.)
        return LookupResult(rows[0]['fields'], rows[0], rows[0]['confidence'])
