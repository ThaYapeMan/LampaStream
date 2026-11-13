"""Read available file tags in acquisition work; never persist audio or file paths."""
import json
import subprocess

from .registry import Identity
from .store import ProviderStore, fingerprint_key


def capture(path, grid, database):
    key = fingerprint_key(grid.audio_fingerprint)
    if key is None:
        return
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags',
                             '-of', 'json', str(path)], capture_output=True, text=True,
                            check=True, timeout=5)
    tags = json.loads(result.stdout).get('format', {}).get('tags', {})
    # Only normalized tempo inputs enter metadata; arbitrary comments can include
    # filesystem paths, and neither a path nor a media URL belongs in the store.
    tags = {name: value for name, value in tags.items() if name.casefold() in ('bpm', 'tbpm')}
    if tags:
        ProviderStore(database).acquire(Identity(
            key, duration=grid.duration, fingerprint=grid.audio_fingerprint, tags=tags))
