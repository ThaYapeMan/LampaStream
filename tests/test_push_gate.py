"""Master push gate syntax, documented coverage, ordering and fail-fast behavior."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_gate_shell_syntax_and_documented_steps():
    for name in (
        "scripts/check-before-push.sh",
        "scripts/install-git-hooks.sh",
        ".githooks/pre-push",
    ):
        subprocess.run(["bash", "-n", str(ROOT / name)], check=True)
    gate = (ROOT / "scripts/check-before-push.sh").read_text()
    for command in (
        "ruff check .",
        "LAMPASTREAM_REQUIRE_NATIVE=1 python3 -m pytest -v",
        "npm --prefix web test",
        "npm --prefix web run test:e2e",
        "npm --prefix web run build",
    ):
        assert command in gate
        for doc in ("testing.md", "development.md"):
            assert command in (ROOT / "docs" / doc).read_text()


@pytest.mark.parametrize("failure", ["", "ruff", "backend", "browser"])
def test_gate_runs_in_order_and_stops_on_first_failure(tmp_path, failure):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check-before-push.sh").write_text(
        (ROOT / "scripts/check-before-push.sh").read_text()
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "steps"
    for name in ("ruff", "python3", "npm", "git"):
        command = bin_dir / name
        command.write_text("""#!/usr/bin/env bash
label=$(basename "$0")
[[ "$label $*" != *'pytest'* ]] || label=backend
[[ "$label $*" != *'test:e2e'* ]] || label=browser
echo "$label $*" >> "$GATE_LOG"
[[ "$label" != "$GATE_FAILURE" ]] || exit 7
""")
        command.chmod(0o755)
    result = subprocess.run(
        ["bash", str(scripts / "check-before-push.sh")],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": str(bin_dir) + ":" + os.environ["PATH"],
            "GATE_LOG": str(log),
            "GATE_FAILURE": failure,
        },
    )
    labels = [line.split()[0] for line in log.read_text().splitlines()]
    expected = ["ruff", "python3", "backend", "npm", "browser", "npm", "git"]
    if failure:
        assert result.returncode == 7
        assert "LOCAL GATE FAILED" in result.stderr
        assert labels == expected[: expected.index(failure) + 1]
    else:
        assert result.returncode == 0
        assert labels == expected
        assert "LOCAL GATE PASSED" in result.stdout


def test_installed_hook_gates_only_master(tmp_path):
    import shutil

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "test",
    )
    (tmp_path / ".githooks").mkdir()
    shutil.copy(ROOT / ".githooks/pre-push", tmp_path / ".githooks/pre-push")
    (tmp_path / "scripts").mkdir()
    gate = tmp_path / "scripts/check-before-push.sh"
    gate.write_text("#!/bin/sh\necho gated >> gate-runs\n")
    gate.chmod(0o755)
    subprocess.run(["bash", str(ROOT / "scripts/install-git-hooks.sh")], cwd=tmp_path, check=True)
    hook = tmp_path / ".git/hooks/pre-push"
    head = git("rev-parse", "HEAD")
    for target in ("refs/heads/feature", "refs/heads/master"):
        result = subprocess.run(
            [str(hook), "origin", "unused"],
            cwd=tmp_path,
            input=f"refs/heads/master {head} {target} {'0' * 40}\n",
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "gate-runs").read_text().splitlines() == ["gated"]
