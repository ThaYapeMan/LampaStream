"""Build the editable checkout's native CAVA library with the wheel compiler recipe."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def build_cavacore(root: str | Path, output: str | Path) -> None:
    """Compile the vendored CAVA core for a wheel or an editable checkout."""
    cava_dir = Path(root) / "src" / "lampastream" / "cavacore"
    out = Path(output)

    # Pre-flight: fail fast with an actionable message if build tools are absent.
    # scripts/install-lampastream.sh installs these before calling pip install.
    if shutil.which("gcc") is None:
        raise RuntimeError(
            "cavacore build requires gcc, which was not found in PATH.\n"
            "Run the standard LampaStream installer (installs this automatically):\n"
            "  bash scripts/install-lampastream.sh\n"
            "Or install manually:  apt install build-essential"
        )

    # Check that fftw3.h is reachable by verifying the compiler can find it.
    fftw_check = subprocess.run(
        ["gcc", "-x", "c", "-fsyntax-only", "-"],
        input="#include <fftw3.h>\n",
        capture_output=True,
        text=True,
    )
    if fftw_check.returncode != 0:
        raise RuntimeError(
            "cavacore build requires libfftw3-dev (fftw3.h not found by gcc).\n"
            "Run the standard LampaStream installer (installs this automatically):\n"
            "  bash scripts/install-lampastream.sh\n"
            "Or install manually:  apt install libfftw3-dev"
        )

    cmd = [
        "gcc",
        "-shared",
        "-fPIC",
        "-O2",
        "-o", str(out),
        str(cava_dir / "cavacore.c"),
        str(cava_dir / "_bridge.c"),
        "-lfftw3",
        "-lm",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            "cavacore native build failed.\n"
            "Run the standard LampaStream installer:  bash scripts/install-lampastream.sh\n"
            f"Command: {' '.join(cmd)}\n"
            f"Compiler output:\n{result.stderr.strip()}"
        )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    output = root / "src" / "lampastream" / "cavacore" / "_libcavacore.so"
    build_cavacore(root, output)
    print(f"Built {output}")
