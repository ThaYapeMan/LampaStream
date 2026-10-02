"""Read-only installed-artifact verification; invoke with the installed python -I -B.

Validates existing data before constructing the app. Does not activate a player,
consume ingress, or invoke startup hooks; missing data is never created in check
mode. Native execution is an isolated smoke test.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

import lampastream
from lampastream.airplay_config import LEGACY_TIMING, SHAIRPORT_REVISION, timing_settings
from lampastream.cavacore import CavaCoreBackend
from lampastream.migration import migrate_file


def verify_player(manifest: dict, binary: Path = Path('/usr/local/bin/yeney-player')) -> None:
    assert manifest['yeney_core_revision'] == '13e606f452d9a2ae729f9590ec4ea696ab4dbcde'
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == manifest['yeney_player_sha256']


def verify_airplay(manifest: dict, receiver_config: str) -> None:
    assert manifest.get('airplay_delivery_margin_ms') == 0, 'AirPlay timing contract unverified'
    assert manifest.get('airplay_timing_policy') == 'receiver-defaults', (
        'AirPlay timing contract unverified')
    assert manifest.get('shairport_revision') == SHAIRPORT_REVISION, (
        'AirPlay timing contract unverified')
    settings = timing_settings(receiver_config)
    assert not any(settings.get(key) == value for key, value in LEGACY_TIMING.items()), (
        'Unsafe legacy AirPlay timing setting remains')


def main() -> None:
    commit, short, config = sys.argv[1:]
    root = Path(sys.prefix).resolve()
    package = Path(lampastream.__file__).resolve().parent
    assert package.is_relative_to(root), f'Import outside installed environment: {package}'
    assert lampastream.__git_hash__ == short, (lampastream.__git_hash__, short)
    manifest = json.loads((root.parent / 'installation.json').read_text())
    assert manifest['commit'] == commit
    assert manifest['short_commit'] == short
    verify_player(manifest)
    assert not migrate_file(Path(config), check=True), 'Migration required'
    receiver_config = Path('/usr/local/etc/shairport-sync.conf').read_text()
    for setting in ('output_backend = "pipe"', '/run/lampastream/airplay.pcm',
                    'output_rate = 44100', 'output_format = "S16_LE"', 'output_channels = 2'):
        assert setting in receiver_config, f'Incompatible receiver configuration: {setting}'
    verify_airplay(manifest, receiver_config)
    assert manifest.get('airplay_early_tap_version') == 1, 'Early-tap build provenance missing'
    assert 'early_tap_name = "/run/lampastream/airplay-early.pcm";' in receiver_config
    assert Path('/run/lampastream/airplay-early.pcm').is_fifo(), 'Early-tap FIFO missing'
    assert manifest.get('shairport_early_tap_patch_sha256'), 'Early-tap patch provenance missing'
    assert (package / 'webui/index.html').is_file()
    assert list((package / 'webui/assets').glob('*.js')), 'Frontend assets missing'
    os.environ['LAMPASTREAM_CONFIG'] = config
    from lampastream import app

    assert app.app is not None
    backend = CavaCoreBackend(n_bars=30, rate=48000, channels=2)
    try:
        bars = backend.execute(np.full((480, 2), .01, dtype=np.float32))
        assert bars is not None and np.isfinite(bars).all()
    finally:
        backend.close()
    for item in ('Git commit', 'Python environment', 'Installed LampaStream import',
                 'Current persisted schema', 'CAVA native initialization/execution',
                 'Frontend assets', 'yeney-player binary provenance',
                 'AirPlay receiver defaults (no imposed early delivery)'):
        print(f'{item}: PASS')


if __name__ == '__main__':
    main()
