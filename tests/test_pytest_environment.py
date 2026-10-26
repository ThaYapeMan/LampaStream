"""Test workers must not share the controller's import-time application config."""

import os
import subprocess
import sys
from pathlib import Path


def test_xdist_workers_isolate_inherited_application_config(tmp_path):
    controller_config = tmp_path / "config.json"
    controller_config.write_text("controller sentinel")
    env = dict(os.environ, LAMPASTREAM_CONFIG=str(controller_config))
    code = """
import os
import runpy
from types import SimpleNamespace
configure = runpy.run_path('tests/conftest.py')['pytest_configure']
configure(SimpleNamespace(workerinput={'workerid': 'gw0'}))
print(os.environ['LAMPASTREAM_CONFIG'])
"""
    paths = [subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
             for _ in range(2)]
    assert len({str(controller_config), *paths}) == 3
    assert all(Path(path).parent.is_dir() for path in paths)
    assert controller_config.read_text() == "controller sentinel"
