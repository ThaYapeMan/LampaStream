#!/usr/bin/env python3
"""Check both receiver patches, in order, against an existing pinned source clone."""

from __future__ import annotations

import argparse
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

REVISION = "0b1c4391ffd398e7b145eb4b98416261380adeea"


def check(source):
    archive = subprocess.check_output(["git", "-C", str(source), "archive", REVISION])
    with tempfile.TemporaryDirectory(prefix="lampastream-patch-check-") as directory:
        target = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
            tree.extractall(target, filter="data")
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        patches = [
            Path(__file__).resolve().parent / "patches" / name
            for name in (
                "shairport-sync-0001-setpeers.patch",
                "shairport-sync-0002-early-tap.patch",
            )
        ]
        print("Pinned shairport-sync: " + REVISION, flush=True)
        for patch in patches:
            for action in [["--check"], []]:
                subprocess.run(["git", "-C", str(target), "apply", *action, str(patch)], check=True)
            print("PASS: forward application: " + patch.name, flush=True)
        for patch in patches:
            subprocess.run(
                ["git", "-C", str(target), "apply", "--check", "--reverse", str(patch)], check=True
            )
            print("PASS: already-applied detection: " + patch.name, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    check(parser.parse_args().source)
