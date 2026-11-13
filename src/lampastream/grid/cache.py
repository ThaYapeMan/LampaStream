"""SQLite-backed content cache; historical JSON is installer-migration-only."""
from pathlib import Path

from .database import GridDatabase


class GridCache:
    def __init__(self, root=None, limit=2000):
        self.path = GridDatabase().path if root is None else Path(root)/'grids.db'
        self.root = self.path.parent/'grids' if root is None else Path(root)
        self.limit = limit
        self.database = GridDatabase(self.path, limit=limit)

    def get(self, identity):
        return self.database.get(identity) if self.path.is_file() else None

    def get_hash(self, key):
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            return None
        return self.database.get_hash(key) if self.path.is_file() else None

    def put(self, identity, grid):
        if not self.path.exists():
            if any(self.root.glob('*.json')):
                raise ValueError('Grid database migration required; run the installer')
            GridDatabase.create(self.path, limit=self.limit)
        self.database.put(identity, grid)
