"""V2 response persistence and state-preserving live application."""
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from lampastream.migration import convert
from lampastream.models import Analyser, Profile
from lampastream.player_manager import PlayerManager, _make_canonical_pipeline
from lampastream.schema import empty_config, validate_current
from lampastream.spectrum_engine import SharedAnalysis, V2SpectrumEngine, make_spectrum_engine
from lampastream.sync_engine import SyncEngine


@pytest.mark.parametrize('value', [0.049, 1.001, float('nan'), float('inf'), None, True])
def test_model_rejects_invalid_response(value):
    with pytest.raises(ValueError, match='bar_falloff_s'):
        Analyser(bar_falloff_s=value)


def test_model_default_roundtrip_and_schema_bounds():
    analyser = Analyser()
    assert analyser.bar_falloff_s == 0.3
    assert Analyser.from_dict(analyser.to_dict()) == analyser
    data = empty_config()
    data['analysers'] = [analyser.to_dict()]
    validate_current(data)
    data['analysers'][0]['bar_falloff_s'] = 1.1
    with pytest.raises(ValueError, match='bar_falloff_s'):
        validate_current(data)


@pytest.mark.parametrize('version', [0, 1, 2])
def test_migration_fills_response_and_preserves_explicit_value(version):
    data = empty_config()
    data['schema_version'] = version
    row = Analyser().to_dict()
    del row['bar_falloff_s']
    data['analysers'] = [row, Analyser(bar_falloff_s=0.1).to_dict()]
    migrated = convert(data)
    assert [a['bar_falloff_s'] for a in migrated['analysers']] == [0.3, 0.1]
    assert 'bar_falloff_s' not in row
    assert convert(migrated) == migrated


def _feed(engine, mag, position=0):
    pcm = np.zeros((480, 2), dtype=np.float32)
    return engine.feed(pcm, SharedAnalysis([mag], pcm, position, 480))[0].bars


def test_shorter_decay_and_default_exactly_matches_old_coefficient():
    engines = [V2SpectrumEngine(10, 50, 10000), V2SpectrumEngine(10, 50, 10000, 0.3),
               V2SpectrumEngine(10, 50, 10000, 0.05)]
    impulse = np.zeros(1025, dtype=np.float32)
    impulse[100] = 1
    old_bars = _feed(engines[0], impulse)
    assert _feed(engines[1], impulse) == old_bars
    assert _feed(engines[2], impulse) == old_bars
    for hop in range(1, 21):
        old_bars = [value * math.exp(-0.01 / 0.3) for value in old_bars]
        results = [_feed(e, np.zeros(1025, dtype=np.float32), hop * 480) for e in engines]
        assert results[0] == results[1] == old_bars
        assert max(results[2]) < max(results[0])


def test_active_session_applies_without_reset_or_replacement():
    profile = Profile(bar_falloff_s=0.3)
    pipeline = _make_canonical_pipeline(MagicMock(), profile)
    engine = pipeline._spectrum_processor._engine
    impulse = np.ones(1025, dtype=np.float32)
    _feed(engine, impulse)
    smooth, peak = engine.v2_bar_smooth, engine.v2_peak_ema
    sync = SyncEngine.__new__(SyncEngine)
    sync._analyser = pipeline
    sync.profile = profile
    manager = PlayerManager.__new__(PlayerManager)
    manager._active = SimpleNamespace(profile=profile, sync_engine=sync)
    changed = Profile(bar_falloff_s=0.05)
    manager.update_bar_falloff(changed)
    assert sync._analyser is pipeline
    assert engine.v2_bar_smooth is smooth
    assert engine.v2_peak_ema == peak
    assert manager._active.profile is sync.profile is changed
    assert max(_feed(engine, np.zeros(1025, dtype=np.float32))) == math.exp(-0.01 / 0.05)


def test_cavacore_factory_stores_no_v2_conditioning(monkeypatch):
    from lampastream.spectrum_engine import ENGINES
    native = SimpleNamespace(engine_id='cavacore')
    factory = MagicMock(return_value=native)
    monkeypatch.setattr(ENGINES['cavacore'], 'create', factory)
    monkeypatch.setattr(ENGINES['cavacore'], 'check_available', lambda: True)
    assert make_spectrum_engine('cavacore', n_bars=10, lower_hz=50, upper_hz=10000,
                                bar_falloff_s=0.05) is native
    factory.assert_called_once_with(10, 50, 10000)
