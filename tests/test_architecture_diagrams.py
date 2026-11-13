"""Keep generated architecture documentation reproducible."""

import subprocess
import sys
from pathlib import Path


def test_architecture_diagrams_reproduce_committed_svgs(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/render-architecture-diagrams.py"),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )
    committed = root / "docs/diagrams"
    expected = {"end-to-end.svg", "beat-source-decision.svg", "analysis-target.svg",
                "track-identity.svg", "stream-buffer.svg"}
    assert {path.name for path in tmp_path.iterdir()} == expected
    assert {path.name for path in committed.glob("*.svg")} == expected
    for name in sorted(expected):
        assert (tmp_path / name).read_bytes() == (committed / name).read_bytes(), name
