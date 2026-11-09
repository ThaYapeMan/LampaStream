"""The lighting gate changes admission only, not candidate identity or timing."""
import json
from dataclasses import replace

import pytest

from lampastream.beat_accents import RelativeOnsetGate
from lampastream.migration import migrate_file
from lampastream.models import EnergyProfile
from lampastream.schema import empty_config, validate_current
from lampastream.types import OnsetEnvelopeFrame, OnsetEvent


def candidate(t, value, bands=frozenset({'all'})):
    sample = round(t*48000)
    return OnsetEvent(('epoch','all',sample), 'epoch',sample,sample+480,1,
                      1.,value,1.,bands,'all')


def observe(gate, t, value, **bands):
    gate.observe('epoch', OnsetEnvelopeFrame(round(t*48000), full=value, **bands))


def test_constant_envelope_never_opens_gate_even_with_zero_mad():
    gate = RelativeOnsetGate()
    for i in range(200):
        observe(gate, i*.05, 1.)
        assert not gate.accepts(candidate(i*.05,1.))


def test_kick_six_spreads_above_background_and_refractory():
    gate = RelativeOnsetGate(k=4,full_k=5,refractory_ms=120)
    for i in range(60):
        observe(gate, i*.05, (1.,2.,3.)[i%3])
    assert gate.reference(3.) == (2.,1.)
    observe(gate,3.,8.)
    assert gate.accepts(candidate(3.,8.))
    observe(gate,3.06,8.)
    assert not gate.accepts(candidate(3.06,8.))
    # Candidates do not train the reference: all observed frames do.
    assert gate.reference(3.06) == (2.,1.)
    assert gate.accepts(candidate(3.2,8.))


def test_equal_periodic_kicks_on_quiet_background_all_fire():
    gate = RelativeOnsetGate(k=6,full_k=7)
    fired = []
    for i in range(401):
        kick = i > 0 and i%50 == 0
        observe(gate,i*.01,10. if kick else (1.,1.1,.9)[i%3])
        if kick:
            fired.append(gate.accepts(candidate(i*.01,10.)))
    assert fired == [True]*8


def test_bass_preference_uses_bass_background_and_full_threshold():
    gate = RelativeOnsetGate(k=2,full_k=4)
    for i in range(30):
        observe(gate,i*.02,(9.,10.,11.)[i%3],bass=(.9,1.,1.1)[i%3])
    # Bass at +3 MAD passes k=2 despite a much louder full-band background.
    assert gate.accepts(candidate(.6,10.,frozenset({'bass','mid'})),1.3)
    assert not gate.accepts(candidate(.8,13.))  # full is only +3 MAD
    assert gate.accepts(candidate(1.,15.))


def test_absolute_minimum_epoch_reset_live_edit_and_duplicate_identity():
    gate = RelativeOnsetGate()
    observe(gate,0.,.001)
    assert not gate.accepts(candidate(.2,.01))
    assert gate.accepts(candidate(.4,.1))
    assert not gate.accepts(candidate(.4,.1))
    before=dict(gate.history)
    gate.configure(3.,3.,160.,4.,.02)
    assert gate.history == before
    assert not gate.accepts(candidate(.46,1.))
    assert gate.accepts(candidate(.6,1.))
    assert not gate.accepts(replace(candidate(0.,10.),epoch='new',id=('new','all',0)))
    assert not gate.history


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
            observe(gate,i*.1,1.)
            assert not gate.accepts(candidate(i*.1,1.))
        history=dict(gate.history)
        engine.update_render(replace(profile,onset_relative_k=1.5,onset_full_k=2.5,
                                     onset_reference_window_s=2.,onset_refractory_ms=80.))
        assert engine._analyser is pipeline and engine._onset_accent_gate is gate
        assert gate.history==history
        assert (gate.k,gate.full_k,gate.window_s,gate.refractory_s)==(1.5,2.5,2.,.08)
        assert gate.accepts(candidate(2.1,2.7))
    finally:
        pipeline.stop()


def test_real_pipeline_tap_contains_non_peaks_and_matches_raw_candidate_units():
    import numpy as np

    from lampastream.canonicalizer import AnalysisPcmFrame
    from lampastream.models import Profile
    from lampastream.player_manager import _make_canonical_pipeline

    pipeline = _make_canonical_pipeline(None,Profile())
    pcm = np.zeros((48000*3,2),dtype=np.float32)
    for start in range(24000,len(pcm)-4800,24000):
        wave = np.sin(np.arange(4800)*2*np.pi*80/48000)*np.exp(-np.arange(4800)/800)
        pcm[start:start+4800] = wave[:,None]
    records = []
    try:
        for start in range(0,len(pcm),480):
            chunk = pcm[start:start+480]
            chunk.setflags(write=False)
            records.extend(pipeline.feed(AnalysisPcmFrame(chunk,start,'tap','offline',False)))
        records.extend(pipeline.end_of_stream())
        frames = [frame for record in records for frame in record.features.onset_raw_frames]
        candidates = [event for record in records for event in record.features.diagnostic_events]
        assert candidates
        assert len(frames) > 250 and len(frames) > len(candidates)*10
        assert len({frame.sample_pos for frame in frames}) == len(frames)
        assert any(frame.full == 0 for frame in frames)
        raw = {frame.sample_pos:frame.full for frame in frames}
        assert all(raw[event.candidate_sample] == event.strength_raw for event in candidates)
    finally:
        pipeline.stop()


def test_reference_excludes_future_frames_and_expires_old_frames():
    gate = RelativeOnsetGate(window_s=3.)
    for i in range(401):
        observe(gate,i*.01,1. if i < 350 else 100.)
    # A delayed candidate uses its sample time, not the latest observed envelope.
    assert gate.reference(3.4) == (1.,0.)
    assert gate.accepts(candidate(3.4,2.))
    observe(gate,10.,100.)
    assert gate.reference(10.) == (100.,0.)
    assert min(gate.history) >= 6.
