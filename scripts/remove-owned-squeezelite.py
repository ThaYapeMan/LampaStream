"""Remove only the previous installer-owned fork, proven by its manifest digest."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def remove_owned_binary(binary: Path, manifest_path: Path) -> bool:
    # Never follow a symlink to a packaged or foreign executable.
    if binary.is_symlink() or not binary.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict):
        return False
    digest = manifest.get('squeezelite_sha256')
    if not isinstance(digest, str) or hashlib.sha256(binary.read_bytes()).hexdigest() != digest:
        return False
    # Package ownership wins even if a stale manifest happens to match the bytes.
    try:
        ownership = subprocess.run(['dpkg-query', '-S', str(binary)],
                                   capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if ownership.returncode != 1:  # 0 = packaged; other errors are not proof of ownership
        return False
    binary.unlink()
    print(f'Removed previous LampaStream fork: {binary}')
    return True


if __name__ == '__main__':
    remove_owned_binary(Path('/usr/local/bin/squeezelite'), Path(sys.argv[1]))
