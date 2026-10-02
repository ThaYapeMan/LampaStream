#!/usr/bin/env python3
"""Conservative release retention and preflight disk-space check."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

MINIMUM_FREE = 1_500_000_000


def active_release(prefix, *, first_install=False):
    link = prefix / ".venv"
    if not os.path.lexists(link) and first_install:
        return None
    try:
        target = link.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Refusing to prune: .venv cannot be resolved") from exc
    if first_install and not link.is_symlink() and (target / "pyvenv.cfg").is_file():
        return None  # existing installer archives this legacy venv inside the new release
    releases = (prefix / "releases").resolve()
    if target.name != "venv" or target.parent.parent != releases:
        raise ValueError("Refusing to prune: .venv does not point to a managed release")
    return target.parent


def candidates(prefix, active, previous=None):
    releases = prefix / "releases"
    if not releases.exists():
        return []
    return sorted(
        p
        for p in releases.iterdir()
        if p.is_dir() and not p.is_symlink() and p.resolve() not in {active, previous}
    )


def check_space(prefix, *, free=None):
    active = active_release(prefix, first_install=True)
    # Legacy checkout-local environments are migrated by the existing installer;
    # pruning is deliberately deferred until the new managed pointer is verified.
    filesystem = prefix
    while not filesystem.exists():
        filesystem = filesystem.parent
    free = shutil.disk_usage(filesystem).free if free is None else free
    if free < MINIMUM_FREE:
        names = ", ".join(p.name for p in candidates(prefix, active)) or "none"
        raise ValueError(
            "Not enough free space: at least 1.5 GB is required before creating "
            "a release. After a successful switch, cleanup would remove inactive "
            f"and failed-run release directories (keeping active and previous): {names}. "
            "Free space and retry; the active release has not been deleted."
        )
    return active


def prune(prefix, previous=None):
    active = active_release(prefix)  # must resolve before any destructive operation
    if previous is not None:
        previous = previous.resolve(strict=True)
        if previous.parent != (prefix / "releases").resolve() or previous.is_symlink():
            raise ValueError("Refusing to prune: previous release is not managed")
    removed = []
    for path in candidates(prefix, active, previous):
        # Recheck the live pointer before each deletion, even under the installer lock.
        if active_release(prefix) != active:
            raise ValueError("Refusing to prune: active release changed during cleanup")
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "previous", "prune"])
    parser.add_argument("prefix", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "check":
            check_space(args.prefix)
        elif args.action == "previous":
            active = active_release(args.prefix, first_install=True)
            print(active or "")
        else:
            for name in prune(args.prefix, args.previous):
                print("Removed inactive release: " + name)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
