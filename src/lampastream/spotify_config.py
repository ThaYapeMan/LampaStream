"""Managed external receiver contract, not a Spotify protocol implementation."""
import json
from pathlib import Path

# Config/schema, API and pipe driver verified at go-librespot v0.10.0,
# commit 57d7278d94a9233060c2a6238f5926ffd1e72de4. Keep setup-spotify.sh pinned too.
SPOTIFY_CONFIG = Path("/etc/lampastream-spotify/config.yml")
SPOTIFY_STATUS_URL = "http://127.0.0.1:3678/status"


def receiver_config(name: str) -> str:
    # JSON strings are also YAML strings: quote arbitrary display names safely.
    return (
        '# Managed by LampaStream; go-librespot v0.10.0.\n'
        f'device_name: {json.dumps(name)}\n'
        'audio_backend: pipe\n'
        'audio_output_pipe: /run/lampastream-spotify/spotify.pcm\n'
        'audio_output_pipe_format: s16le\n'
        'audio_output_pipe_wait_for_reader: true\n'
        'external_volume: true\n'
        'zeroconf_enabled: true\n'
        'zeroconf_backend: avahi\n'
        'credentials:\n'
        '  type: zeroconf\n'
        '  zeroconf:\n'
        '    persist_credentials: false\n'
        'server:\n'
        '  enabled: true\n'
        '  address: 127.0.0.1\n'
        '  port: 3678\n'
    )
