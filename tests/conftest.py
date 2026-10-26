import os
import sys
import tempfile

# Make scripts/ importable for test_capture_energy.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def pytest_configure(config):
    """Point LAMPASTREAM_CONFIG at a writable temp path before any module imports app.py.

    app.py creates Storage(CONFIG_PATH) at module level, which calls mkdir().
    Without this, importing the test module in a read-only environment (e.g. CI)
    raises PermissionError on /etc/lampastream.
    """
    # xdist workers inherit the controller environment. Each process needs its own
    # Storage path: Storage uses a fixed config.tmp name during atomic writes.
    if "LAMPASTREAM_CONFIG" not in os.environ or hasattr(config, "workerinput"):
        tmpdir = tempfile.mkdtemp(prefix="lampastream_test_")
        os.environ["LAMPASTREAM_CONFIG"] = os.path.join(tmpdir, "config.json")


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def replay_cache(tmp_path_factory, request):
    from onset_regression_support import ReplayCache

    base = tmp_path_factory.getbasetemp()
    if hasattr(request.config, "workerinput"):
        base = base.parent
    return ReplayCache(base / "shared-replay-cache")


def pytest_xdist_auto_num_workers(config):
    """Bound auto workers on shared hosts; respect a smaller CPU affinity."""
    return min(4, len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity")
               else os.cpu_count() or 1)
