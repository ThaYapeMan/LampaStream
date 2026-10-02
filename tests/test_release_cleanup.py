"""Release pruning never deletes the executable selected by .venv."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "manage_releases", Path(__file__).resolve().parents[1] / "scripts/manage-releases.py"
)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def release(prefix, name):
    path = prefix / "releases" / name
    (path / "venv").mkdir(parents=True)
    return path


def test_prune_retains_active_and_previous_and_removes_failed_runs(tmp_path):
    previous = release(tmp_path, "previous")
    active = release(tmp_path, "active")
    release(tmp_path, "failed-run")
    release(tmp_path, "old")
    (tmp_path / ".venv").symlink_to(active / "venv")
    assert manager.prune(tmp_path, previous) == ["failed-run", "old"]
    assert active.exists() and previous.exists()
    assert (tmp_path / ".venv").resolve() == active / "venv"
    assert manager.prune(tmp_path, previous) == []


@pytest.mark.parametrize("broken", ["missing", "dangling", "outside"])
def test_prune_refuses_unresolvable_or_unmanaged_venv(tmp_path, broken):
    candidate = release(tmp_path, "must-keep")
    if broken == "dangling":
        (tmp_path / ".venv").symlink_to(tmp_path / "missing")
    elif broken == "outside":
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / ".venv").symlink_to(outside)
    with pytest.raises(ValueError, match="Refusing to prune"):
        manager.prune(tmp_path)
    assert candidate.exists()


def test_disk_check_fails_early_and_names_cleanup_without_deleting(tmp_path):
    active = release(tmp_path, "active")
    failed = release(tmp_path, "failed-install")
    (tmp_path / ".venv").symlink_to(active / "venv")
    with pytest.raises(ValueError, match="1.5 GB.*failed-install"):
        manager.check_space(tmp_path, free=manager.MINIMUM_FREE - 1)
    assert active.exists() and failed.exists()
    assert manager.check_space(tmp_path, free=manager.MINIMUM_FREE) == active


def test_first_install_check_and_legacy_venv_do_not_prune(tmp_path):
    assert manager.check_space(tmp_path, free=manager.MINIMUM_FREE) is None
    legacy = tmp_path / ".venv"
    legacy.mkdir()
    (legacy / "pyvenv.cfg").write_text("home = /usr/bin")
    assert manager.check_space(tmp_path, free=manager.MINIMUM_FREE) is None
    with pytest.raises(ValueError, match="Refusing to prune"):
        manager.prune(tmp_path)


def test_installer_checks_before_release_and_prunes_after_service_health():
    script = (Path(__file__).resolve().parents[1] / "scripts/install-lampastream.sh").read_text()
    assert script.index('manage-releases.py" check') < script.index("WORK=$(mktemp")
    assert script.index('manage-releases.py" previous') < script.index(
        'mv -Tf "$PREFIX/.venv.next"'
    )
    assert script.index("http://127.0.0.1:8420/api/status") < script.index(
        'manage-releases.py" prune'
    )
