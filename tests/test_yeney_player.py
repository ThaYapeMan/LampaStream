"""Real pinned producer/consumer integration and installation provenance boundaries."""
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from lampastream.pcm_source import DataResult, SqueezeliteShmStereoSource

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'third_party/yeney-core'
REVISION = '13e606f452d9a2ae729f9590ec4ea696ab4dbcde'


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('revision', [REVISION, 'foreign'])
def test_manifest_and_verifier(tmp_path, revision):
    writer = load_script('write-install-manifest.py')
    verifier = load_script('verify-install.py')
    binary = tmp_path / 'yeney-player'
    binary.write_bytes(b'built player')
    if revision != REVISION:
        with pytest.raises(AssertionError):
            writer.write_manifest('abcdef12', 'abcdef1', tmp_path, revision, binary)
        return
    writer.write_manifest('abcdef12', 'abcdef1', tmp_path, revision, binary)
    manifest = json.loads((tmp_path / 'installation.json').read_text())
    assert manifest == {
        'commit': 'abcdef12', 'short_commit': 'abcdef1', 'yeney_core_revision': REVISION,
        'shairport_revision': '0b1c4391ffd398e7b145eb4b98416261380adeea',
        'airplay_delivery_margin_ms': 0,
        'airplay_timing_policy': 'receiver-defaults',
        'airplay_early_tap_version': 1,
        'shairport_early_tap_patch_sha256': hashlib.sha256(
            (ROOT / 'scripts/patches/shairport-sync-0002-early-tap.patch').read_bytes()
        ).hexdigest(),
        'yeney_player_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    verifier.verify_player(manifest, binary)
    with pytest.raises(AssertionError):
        verifier.verify_player(dict(manifest, yeney_core_revision='foreign'), binary)
    binary.write_bytes(b'replaced binary')
    with pytest.raises(AssertionError):
        verifier.verify_player(manifest, binary)


@pytest.mark.parametrize('case', ['owned', 'foreign', 'packaged', 'missing', 'corrupt',
                                  'no_digest', 'symlink', 'package_query_error'])
def test_remove_only_owned_old_fork(tmp_path, case, monkeypatch):
    cleanup = load_script('remove-owned-squeezelite.py')
    binary = tmp_path / 'squeezelite'
    manifest = tmp_path / 'installation.json'
    binary.write_bytes(b'old owned fork')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({'squeezelite_sha256': digest}))
    ownership_code = 0 if case == 'packaged' else 2 if case == 'package_query_error' else 1
    monkeypatch.setattr(cleanup.subprocess, 'run',
                        lambda *args, **kw: subprocess.CompletedProcess(args[0], ownership_code))
    if case == 'foreign':
        binary.write_bytes(case.encode())
    elif case == 'missing':
        manifest.unlink()
    elif case == 'corrupt':
        manifest.write_text('{')
    elif case == 'no_digest':
        manifest.write_text('{}')
    elif case == 'symlink':
        target = tmp_path / 'packaged-player'
        binary.rename(target)
        binary.symlink_to(target)
    removed = cleanup.remove_owned_binary(binary, manifest)
    assert removed == (case == 'owned')
    assert binary.exists() == (case != 'owned')
    if case == 'symlink':
        assert target.read_bytes() == b'old owned fork'


def test_old_manifest_read_before_release_switch():
    installer = (ROOT / 'scripts/install-lampastream.sh').read_text()
    assert installer.index('remove-owned-squeezelite.py') < installer.index(
        'write-install-manifest.py')
    assert '"$PREFIX/.venv/../installation.json"' in installer
    assert '"$RELEASE" "$YENEY_CORE_REVISION"' in installer


def test_real_yeney_player_shm_v1(tmp_path, monkeypatch):
    for tool in ('gcc', 'g++', 'make', 'ar'):
        if shutil.which(tool) is None:
            reason = f'yeney-player integration: missing {tool}'
            print(f'SKIP {reason}', flush=True)
            pytest.skip(reason)
    probe = subprocess.run(['g++', '-x', 'c++', '-', '-lFLAC',
                            '-o', str(tmp_path / 'flac-probe')],
                           input='#include <FLAC/stream_decoder.h>\nint main() { return 0; }\n',
                           capture_output=True, text=True)
    if probe.returncode:
        reason = 'yeney-player integration: missing libflac-dev headers or linker library'
        print(f'SKIP {reason}', flush=True)
        pytest.skip(reason)
    assert subprocess.check_output(['git', '-C', str(CORE), 'rev-parse', 'HEAD'],
                                   text=True).strip() == REVISION
    build = tmp_path / 'core'
    # Build outside the submodule; never alter its sources or build state.
    shutil.copytree(CORE, build, ignore=shutil.ignore_patterns('.git', 'tests', '*.o', '*.d',
                                                            'libyeneycore.a'))
    result = subprocess.run(['make', '-C', str(build), '-j2', 'yeney-player'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    oracle_spec = importlib.util.spec_from_file_location(
        'yeney_fake_lms', CORE / 'tests/fake_lms.py')
    oracle = importlib.util.module_from_spec(oracle_spec)
    oracle_spec.loader.exec_module(oracle)
    monkeypatch.setattr(oracle, 'ROOT', build)
    mac = '02:7e:' + ':'.join(f'{b:02x}' for b in os.getpid().to_bytes(4, 'big'))
    path = Path('/dev/shm/squeezelite-' + mac)
    source = SqueezeliteShmStereoSource()
    try:
        with oracle.Session(app=True, sink='shm', app_args=['-v'], mac=mac) as session:
            source.open(mac, require_v1=True)
            body, _ = oracle.pcm(rate=44100, bits=16, seconds=.4)
            expected = np.frombuffer(body, dtype='<i2').reshape(-1, 2)
            session.lms.send('audg', struct.pack('!IIBBII', 0, 0, 1, 0, 0, 0))
            session.lms.strm('s', session.source(body), bits=16)
            deadline = time.monotonic() + 5
            received = 0
            last_end = None
            while last_end != len(expected) and time.monotonic() < deadline:
                result = source.read()
                if isinstance(result, DataResult):
                    frame = result.frame
                    actual = (frame.samples * 32768).astype('<i2')
                    start = frame.source_sample_pos
                    if last_end is not None:
                        assert start == last_end
                    last_end = start + len(actual)
                    np.testing.assert_array_equal(actual, expected[start:start + len(actual)])
                    assert frame.sample_rate == 44100
                    received += len(actual)
                time.sleep(.002)
            # The unchanged consumer invalidates the initial running transition.
            # Validate continuous exact PCM after that boundary through the final frame.
            assert last_end == len(expected)
            assert received > len(expected) * .9
            session.lms.wait('STMu')
    finally:
        source.close()
        path.unlink(missing_ok=True)
