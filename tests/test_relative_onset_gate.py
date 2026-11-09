"""The lighting gate changes admission only, not candidate identity or timing."""
import json
from dataclasses import replace

import pytest

from lampastream.beat_accents import RelativeOnsetGate
from lampastream.migration import migrate_file
from lampastream.models import EnergyProfile
from lampastream.schema import empty_config, validate_current
from lampastream.types import OnsetEvent


def candidate(t, value, bands=frozenset({'all'})):
    sample = round(t*48000)
    return OnsetEvent(('epoch','all',sample), 'epoch',sample,sample+480,1,
                      1.,value,1.,bands,'all')


def test_constant_level_never_opens_relative_gate():
    gate = RelativeOnsetGate()
    assert not any(gate.accepts(candidate(i*.05,1.)) for i in range(200))


def test_threefold_jump_fires_once_and_rejected_jump_trains_reference():
    gate = RelativeOnsetGate(k=2,full_k=2,refractory_ms=120)
    for i in range(60):
        assert not gate.accepts(candidate(i*.05,1.))
    assert gate.accepts(candidate(3.,3.))
    assert not gate.accepts(candidate(3.06,3.))
    assert gate.history[-1][3] == candidate(3.06,3.).id
    assert all(row[0] >= .06 for row in gate.history)
    assert not gate.accepts(candidate(3.07,3.))


def test_bass_preference_uses_bass_reference_and_stricter_full_threshold():
    gate = RelativeOnsetGate(k=2,full_k=3)
    for i in range(10):
        assert not gate.accepts(candidate(i*.1,10.,frozenset({'bass','mid'})),1.)
    assert gate.accepts(candidate(1.,12.,frozenset({'bass','mid'})),2.5)
    assert not gate.accepts(candidate(1.2,25.))  # < 3 * full-band reference
    assert gate.accepts(candidate(1.4,40.))


def test_absolute_minimum_epoch_reset_live_edit_and_duplicate_identity():
    gate = RelativeOnsetGate(k=2,full_k=3)
    assert not gate.accepts(candidate(0.,.001))
    assert not gate.accepts(candidate(.2,.01))  # below detector minimum .02
    assert gate.accepts(candidate(.4,.1))
    assert not gate.accepts(candidate(.4,.1))  # duplicate cannot retrain
    assert len(gate.history)==3
    before=list(gate.history)
    gate.configure(1.5,3.,160.,2.,.02)
    assert gate.history == before
    assert not gate.accepts(candidate(.46,1.))
    assert gate.accepts(candidate(.6,1.))
    assert not gate.accepts(replace(candidate(0.,10.),epoch='new',id=('new','all',0)))
    assert len(gate.history)==1


@pytest.mark.parametrize('values',[{'onset_relative_k':1}, {'onset_reference_window_s':0},
                                  {'onset_refractory_ms':59}, {'onset_refractory_ms':201},
                                  {'onset_full_k':1.5}, {'onset_relative_k':float('inf')}])
def test_invalid_parameters(values):
    with pytest.raises(ValueError):
        EnergyProfile(**values)


def test_schema_three_migration_materializes_four_parameters(tmp_path):
    data=empty_config()
    data['schema_version']=3
    row=EnergyProfile(id='energy').to_dict()
    row['onset_gain_floor']=row.pop('tracker_gain_floor')
    fields=('onset_relative_k','onset_reference_window_s','onset_refractory_ms','onset_full_k')
    for field in fields:
        row.pop(field)
    data['energy_profiles']=[row]
    path=tmp_path/'config.json'
    original=json.dumps(data).encode()
    path.write_bytes(original)
    with pytest.raises(ValueError):
        validate_current(data)
    assert migrate_file(path,check=True) and path.read_bytes()==original
    assert migrate_file(path)
    migrated=json.loads(path.read_bytes())
    assert migrated['schema_version']==4
    assert [migrated['energy_profiles'][0][f] for f in fields]==[2.,3.,120.,3.]
    assert migrated['energy_profiles'][0]['tracker_gain_floor']==.3  # Tracker unchanged
    assert list(tmp_path.glob('*.bak'))[0].read_bytes()==original
    assert not migrate_file(path)
    broken=json.loads(path.read_text())
    broken['energy_profiles'][0].pop('onset_relative_k')
    with pytest.raises(ValueError,match='missing accent settings'):
        validate_current(broken)


def test_engine_relative_edit_preserves_reference_and_analyser():
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline
    from lampastream.sync_engine import SyncEngine

    profile=Profile()
    pipeline=_make_canonical_pipeline(None,profile)
    engine=SyncEngine(None,profile,analyser=pipeline)
    gate=engine._onset_accent_gate
    try:
        for i in range(20):
            assert not gate.accepts(candidate(i*.1,1.))
        history=list(gate.history)
        engine.update_render(replace(profile,onset_relative_k=1.5,onset_full_k=2.5,
                                     onset_reference_window_s=2.,onset_refractory_ms=80.))
        assert engine._analyser is pipeline and engine._onset_accent_gate is gate
        assert gate.history==history
        assert (gate.k,gate.full_k,gate.window_s,gate.refractory_s)==(1.5,2.5,2.,.08)
        assert gate.accepts(candidate(2.1,2.7))
    finally:
        pipeline.stop()
