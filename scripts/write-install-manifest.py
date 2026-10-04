"""Record installed binary provenance after successful builds, before activation."""
import hashlib
import json
import sys
from pathlib import Path


def write_manifest(commit: str, short: str, release: Path, revision: str,
                   binary: Path = Path('/usr/local/bin/yeney-player')) -> None:
    assert revision == '45779a4383929840a46a931fc1519b4778b64a72'
    manifest = {
        'commit': commit, 'short_commit': short,
        'yeney_core_revision': revision,
        'shairport_revision': '0b1c4391ffd398e7b145eb4b98416261380adeea',
        'airplay_delivery_margin_ms': 0,
        'airplay_timing_policy': 'receiver-defaults',
        'airplay_early_tap_version': 1,
        'shairport_early_tap_patch_sha256': hashlib.sha256(
            (Path(__file__).resolve().parent / 'patches/shairport-sync-0002-early-tap.patch')
            .read_bytes()).hexdigest(),
        'yeney_player_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    (release / 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    commit, short, release, revision = sys.argv[1:]
    write_manifest(commit, short, Path(release), revision)
