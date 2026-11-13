"""Operator corrections, persisted through the same provider contract."""
from .registry import LookupResult


class Adapter:
    def lookup(self, identity):
        if not identity.fingerprint or not identity.key.startswith('fp:'):
            raise ValueError('Owner corrections need an audio-fingerprint identity')
        fields = dict(identity.correction or {})
        if not fields:
            raise ValueError('Supply a correction')
        return LookupResult(fields, fields.copy(), 1.)
