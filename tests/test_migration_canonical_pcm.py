"""Retirement of the internal CAVA route uses the existing offline migration."""
import copy
import json

import pytest

from lampastream.migration import convert, migrate_file
from lampastream.models import Analyser
from lampastream.schema import empty_config, validate_current


@pytest.mark.parametrize('version', [0, 1])
@pytest.mark.parametrize('backend', [None, 'v2', 'cavacore'])
def test_legacy_rows_preserve_every_other_field(version, backend):
    original = empty_config()
    original['schema_version'] = version
    row = Analyser(id='legacy', use_hpss_separation=True, band_normalise=True).to_dict()
    row['bars_source'] = 'cava'
    if backend is None:
        row.pop('spectrum_backend')
    else:
        row['spectrum_backend'] = backend
    canonical = Analyser(id='canonical', spectrum_backend='cavacore').to_dict()
    original['analysers'] = [row, canonical]
    snapshot = copy.deepcopy(original)
    migrated = convert(original)
    expected = dict(row, bars_source='pcm_pipeline', spectrum_backend=backend or 'v2')
    assert migrated['analysers'] == [expected, canonical]
    assert original == snapshot
    assert convert(migrated) == migrated
    validate_current(migrated, references=True)


def test_file_backup_check_and_byte_preserving_rerun(tmp_path):
    path = tmp_path / 'config.json'
    config = empty_config()
    config['analysers'] = [dict(id='a', bars_source='cava', use_hpss_separation=True)]
    raw = json.dumps(config).encode()
    path.write_bytes(raw)
    assert migrate_file(path, check=True)
    assert path.read_bytes() == raw
    assert list(tmp_path.glob('*.bak')) == []
    assert migrate_file(path)
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    migrated = path.read_bytes()
    assert not migrate_file(path)
    assert path.read_bytes() == migrated
    assert list(tmp_path.glob('*.bak')) == backups


@pytest.mark.parametrize('rows', [None, {}, [None], ['cava'],
    [dict(id='a', bars_source='unknown')],
    [dict(id='a', bars_source='cava', unknown=1)],
    [dict(id='a', bars_source='cava', spectrum_backend='unknown')],
    [dict(id='a', bars_source='cava', use_hpss_separation='yes')],
    [dict(bars_source='cava')],
    [dict(id='a', bars_source='cava'), dict(id='a')],
])
def test_malformed_rows_fail_without_writing(tmp_path, rows):
    config = empty_config()
    config['analysers'] = rows
    path = tmp_path / 'config.json'
    raw = json.dumps(config).encode()
    path.write_bytes(raw)
    with pytest.raises((ValueError, TypeError)):
        migrate_file(path)
    assert path.read_bytes() == raw
    assert list(tmp_path.glob('*.bak')) == []


def test_current_file_is_exact_noop(tmp_path):
    config = empty_config()
    config['analysers'] = [Analyser(id='a').to_dict()]
    path = tmp_path / 'config.json'
    raw = json.dumps(config).encode()
    path.write_bytes(raw)
    assert not migrate_file(path)
    assert path.read_bytes() == raw
    assert list(tmp_path.glob('*.bak')) == []


def test_runtime_requires_offline_migration(tmp_path):
    from lampastream.storage import Storage

    path = tmp_path / 'config.json'
    data = empty_config()
    data['analysers'] = [dict(id='a', bars_source='cava')]
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='bars_source'):
        Storage(path)
    assert path.read_bytes() == raw
    assert migrate_file(path)
    assert Storage(path).get_analyser('a').bars_source == 'pcm_pipeline'
