"""Record installed binary provenance after successful builds, before activation."""
import hashlib
import json
import sys
from pathlib import Path

commit, short, release = sys.argv[1:]
binary = Path('/usr/local/bin/squeezelite')
manifest = {
    'commit': commit, 'short_commit': short,
    'squeezelite_revision': '0e1667ead996834e355fc51f6a8eb2ea7e55f44b',
    'squeezelite_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
    'producer_objects': ['output_vis.o', 'output_vis_v1.o'],
}
Path(release, 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')
