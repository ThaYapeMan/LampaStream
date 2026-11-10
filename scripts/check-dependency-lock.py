#!/usr/bin/env python3
"""Refuse stale installed versions of exact runtime pins before any gate tests."""
import tomllib
from importlib import metadata
from pathlib import Path

from lampastream.dependency_versions import verify_hue_dependency


def main():
    root = Path(__file__).resolve().parents[1]
    requirements = tomllib.loads((root/'pyproject.toml').read_text())['project']['dependencies']
    verify_hue_dependency(requirements)
    for requirement in requirements:
        if '==' not in requirement:
            continue
        name, expected = requirement.split('==', 1)
        actual = metadata.version(name)
        assert actual == expected, (
            f'Dependency lock mismatch: {name}=={expected}; installed {actual}')
        print(f'Runtime dependency lock: {name} {actual}: PASS')


if __name__ == '__main__':
    main()
