"""Hatchling build hook: write git commit hash and compile cavacore native library.

Runs automatically during `pip install .` (editable or wheel).

Git hash and native library are generated outside the checkout and included in the wheel.
LAMPASTREAM_BUILD_COMMIT supplies the revision for a git-archive build.

cavacore: compiles src/lampastream/cavacore/cavacore.c + _bridge.c into
_libcavacore.so using gcc and libfftw3.  The standard LampaStream installer
(scripts/install-lampastream.sh) installs the required system packages automatically before
calling pip install:
    scripts/native-build-packages.txt
This shared Debian/Ubuntu package list also drives CI and the development/wheel
build instructions in docs/development.md. Python test dependencies are in the
dev extra, not in the production installer or wheel runtime dependencies.
libfftw3-dev pulls in the runtime FFTW3 shared library as a transitive
dependency, so no additional runtime package needs to be listed separately.
If those packages are absent a RuntimeError is raised immediately so that pip
reports the failure clearly with an actionable message.
"""

from __future__ import annotations

import os
import re
import runpy
import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        # Mark wheel as platform-specific (contains a compiled .so).
        build_data["pure_python"] = False
        build_data["infer_tag"] = True
        self._generated = tempfile.TemporaryDirectory(prefix="lampastream-build-")
        try:
            self._write_commit_file()
            self._build_cavacore()
        except Exception:
            self._generated.cleanup()
            raise
        generated = Path(self._generated.name)
        build_data.setdefault("force_include", {}).update({
            str(generated / "_commit.py"): "lampastream/_commit.py",
            str(generated / "_libcavacore.so"): "lampastream/cavacore/_libcavacore.so",
        })

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        self._generated.cleanup()

    def _write_commit_file(self) -> None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.root,
            )
            git_hash = result.stdout.strip()
        except Exception:
            git_hash = "unknown"

        git_hash = os.environ.get("LAMPASTREAM_BUILD_COMMIT", git_hash)
        if git_hash != "unknown" and not re.fullmatch(r"[0-9a-f]{7,40}", git_hash):
            raise ValueError("LAMPASTREAM_BUILD_COMMIT must be a Git hexadecimal revision")
        commit_file = Path(self._generated.name) / "_commit.py"
        commit_file.write_text(f'COMMIT = "{git_hash}"\n')

    def _build_cavacore(self) -> None:
        # run_path also works in the installer's git archive, outside sys.path.
        build_cavacore = runpy.run_path(
            str(Path(self.root) / "scripts" / "build_native.py")
        )["build_cavacore"]
        build_cavacore(self.root, Path(self._generated.name) / "_libcavacore.so")
