"""BPM fields from library tags or normalized sender metadata, never a network lookup."""
from .registry import LookupResult


class Adapter:
    def lookup(self, identity):
        values = {str(k).casefold(): v for k, v in (identity.tags or {}).items()}
        raw = next((values[k] for k in ('tbpm', 'bpm', 'tempo') if k in values), None)
        if raw is None:
            return LookupResult({}, {}, 0.)
        return LookupResult({'tempo': float(raw)}, {'bpm_tag': raw}, .8)
