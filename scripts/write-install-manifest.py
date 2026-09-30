"""Record installed binary provenance after successful builds, before activation."""
import hashlib
import json
import sys
from pathlib import Path


def write_manifest(commit: str, short: str, release: Path, revision: str,
                   binary: Path = Path('/usr/local/bin/yeney-player')) -> None:
    assert revision == '0c4b3699355b9cefd7f05b8591fe5210952c1409'
    manifest = {
        'commit': commit, 'short_commit': short,
        'yeney_core_revision': revision,
        'yeney_player_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    (release / 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    commit, short, release, revision = sys.argv[1:]
    write_manifest(commit, short, Path(release), revision)
