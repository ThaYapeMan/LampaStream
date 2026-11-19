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
    fields = json.loads(result.stdout).get('format', {}).get('tags', {})
    fields = {name.casefold(): value for name, value in fields.items()}
    tags = {name: fields[name] for name in ('bpm', 'tbpm') if name in fields}
    store = ProviderStore(database)
    store.save_file_identity(
        key, album_artist=fields.get('album_artist', fields.get('albumartist', '')),
        isrc=fields.get('isrc', fields.get('tsrc', '')))
    if tags:
        store.lookup('local-tags', Identity(
            key, duration=grid.duration, fingerprint=grid.audio_fingerprint, tags=tags))
