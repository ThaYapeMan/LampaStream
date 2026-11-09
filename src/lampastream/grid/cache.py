"""Atomic content-addressed grid storage with a bounded LRU identity index."""
import hashlib
import json
import os
from pathlib import Path

from . import TrackGrid


class GridCache:
    def __init__(self, root='/var/lib/lampastream/grids', limit=2000):
        self.root = Path(root)
        if limit < 1:
            raise ValueError("Cache limit must be positive")
        self.limit = limit

    def _alias(self, identity):
        return self.root / ('identity-' + hashlib.sha256(identity.encode()).hexdigest() + '.json')

    def get(self, identity):
        try:
            alias = self._alias(identity)
            key = json.loads(alias.read_text())['sha256']
            alias.touch()
            return self.get_hash(key)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def get_hash(self, key):
        try:
            if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                return None
            path = self.root / f'{key}.json'
            grid = TrackGrid.from_dict(json.loads(path.read_text()))
            if grid.file_sha256 != key:
                return None
            path.touch()
            return grid
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, identity, grid):
        self.root.mkdir(parents=True, exist_ok=True)
        self._write(self.root / f'{grid.file_sha256}.json', grid.to_dict())
        self._write(self._alias(identity), {'sha256': grid.file_sha256})
        files = sorted((p for p in self.root.glob('*.json') if not p.name.startswith('identity-')),
                       key=lambda p: p.stat().st_mtime_ns)
        for path in files[:-self.limit]:
            path.unlink(missing_ok=True)
        # Bound aliases as well, and remove aliases whose content has been evicted.
        aliases = sorted(self.root.glob('identity-*.json'), key=lambda p: p.stat().st_mtime_ns)
        for path in aliases[:-self.limit]:
            path.unlink(missing_ok=True)
        for path in self.root.glob('identity-*.json'):
            try:
                key = json.loads(path.read_text())['sha256']
                if not (self.root / f'{key}.json').exists():
                    path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError):
                path.unlink(missing_ok=True)

    @staticmethod
    def _write(path, value):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, allow_nan=False))
        os.replace(temporary, path)
