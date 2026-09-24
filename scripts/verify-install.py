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
from lampastream.cavacore import CavaCoreBackend
from lampastream.migration import migrate_file

commit, short, config = sys.argv[1:]
root = Path(sys.prefix).resolve()
package = Path(lampastream.__file__).resolve().parent
assert package.is_relative_to(root), f'Import outside installed environment: {package}'
assert lampastream.__git_hash__ == short, (lampastream.__git_hash__, short)
manifest = json.loads((root.parent / 'installation.json').read_text())
assert manifest['commit'] == commit
assert manifest['short_commit'] == short
assert manifest['squeezelite_revision'] == '0e1667ead996834e355fc51f6a8eb2ea7e55f44b'
actual_sha = hashlib.sha256(Path('/usr/local/bin/squeezelite').read_bytes()).hexdigest()
assert actual_sha == manifest['squeezelite_sha256']
assert manifest['producer_objects'] == ['output_vis.o', 'output_vis_v1.o']
assert not migrate_file(Path(config), check=True), 'Migration required'
receiver_config = Path('/usr/local/etc/shairport-sync.conf').read_text()
for setting in ('output_backend = "pipe"', '/run/lampastream/airplay.pcm',
                'output_rate = 44100', 'output_format = "S16_LE"', 'output_channels = 2'):
    assert setting in receiver_config, f'Incompatible receiver configuration: {setting}'
assert (package / 'webui/index.html').is_file()
assert list((package / 'webui/assets').glob('*.js')), 'Frontend assets missing'
os.environ['LAMPASTREAM_CONFIG'] = config
import lampastream.app  # noqa: E402

assert lampastream.app.app is not None
backend = CavaCoreBackend(n_bars=30, rate=48000, channels=2)
try:
    bars = backend.execute(np.full((480, 2), .01, dtype=np.float32))
    assert bars is not None and np.isfinite(bars).all()
finally:
    backend.close()
for item in ('Git commit', 'Python environment', 'Installed LampaStream import',
             'Current persisted schema', 'CAVA native initialization/execution',
             'Frontend assets', 'Squeezelite binary provenance'):
    print(f'{item}: PASS')
