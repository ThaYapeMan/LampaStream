"""LIGHTS-01: stream isolation, live transitions and the explicit cutover."""
import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lampastream.beat_accents import RelativeOnsetGate, gain_progress, select_events
from lampastream.beat_trigger import EnergyTrigger
from lampastream.migration import convert, migrate_file
from lampastream.models import Coupling, EnergyProfile, Profile
from lampastream.player_manager import _make_canonical_pipeline
from lampastream.scheduler import Scheduler
from lampastream.schema import SCHEMA_VERSION, empty_config, validate_current
from lampastream.storage import Storage
from lampastream.sync_engine import SyncEngine
from lampastream.trace_output import TraceChannel, TraceOutput
from lampastream.types import AudioFeatures, OnsetEvent, OutputCapabilities, Position


def event(sample=4800, *, predicted=False):
    return OnsetEvent(('test', 'beat' if predicted else 'all', sample), 'test', sample,
                      sample+480, 0, .8, .8, 1., frozenset({'bass'}), 'bass',
                      predicted=predicted, kind='beat')


def features(**kwargs):
    return AudioFeatures([.2]*30, .2, .2, .2, .2, **kwargs)


@pytest.mark.parametrize('mode', ['off', 'onset', 'tracker'])
def test_source_and_clock_anchors(mode):
    raw, grid = event(), event(9600, predicted=True)
    record = SimpleNamespace(sample_pos=4800, features=features(
        diagnostic_events=(raw,), received_monotonic=1., play_monotonic=3.))
    gate = RelativeOnsetGate()
    gate.accepts(replace(raw, id=("test", "bass", 0), candidate_sample=0,
                         strength_raw=.1), .1)
    result = select_events(mode, [grid], [record], gate=gate)
    assert [e.id for e in result] == ([] if mode == 'off' else
                                    [raw.id] if mode == 'onset' else [grid.id])
    if mode == 'onset':
        assert result[0].play_monotonic == 3.
        assert result[0].received_monotonic == 1.
        assert not result[0].predicted


@pytest.mark.parametrize('mode', ['off', 'onset', 'tracker'])
def test_scheduler_intake_and_live_switch(monkeypatch, mode):
    """Exercise actual run(), including future tracker events and mode invalidation."""
    profile = Profile(beat_accent_mode=mode, effect_type='solid')
    analyser = _make_canonical_pipeline(None, profile)
    engine = SyncEngine(None, profile, analyser=analyser)
    output = TraceOutput([TraceChannel(0, Position(0, 0, 0))],
                         capabilities=OutputCapabilities())
    now, intake, modes = [0.], [], []
    original = Scheduler.add

    def observe(self, request, stamp, **kwargs):
        for e in request.events:
            intake.append((engine.profile.beat_accent_mode, e, request.audible, stamp))
        return original(self, request, stamp, **kwargs)

    monkeypatch.setattr(Scheduler, 'add', observe)

    def publish():
        raw = event(round(now[0]*48000)+4800)
        grid = event(round(now[0]*48000)+24000, predicted=True)
        analyser._publish(epoch_id='test', sample_start=raw.candidate_sample,
            sample_end=raw.candidate_sample+480,
            features=features(diagnostic_events=(replace(raw,
                    id=("test", "warm", raw.candidate_sample-480),
                    candidate_sample=raw.candidate_sample-480, strength_raw=.01), raw),
                              onset_events=(grid,),
                              received_monotonic=now[0], play_monotonic=now[0]+.2),
            effective_spectrum_backend='v2', effective_processor_ids=('v2',))

    remaining = [m for m in ['tracker', 'off', 'onset'] if m != mode]
    publish()

    async def tick(dt):
        now[0] += dt
        if remaining:
            next_mode = remaining.pop(0)
            engine.update_render(replace(profile, beat_accent_mode=next_mode))
            modes.append(next_mode)
            publish()
        elif now[0] > .1:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.run(output, clock=lambda: now[0], sleep=tick))
        assert engine._analyser is analyser  # no worker/session replacement
        assert modes
        assert any(m == 'tracker' and e.predicted and audible > stamp
                   for m, e, audible, stamp in intake)
        assert not any(m in {'off', 'onset'} and e.predicted for m, e, _, _ in intake)
        assert any(m == 'onset' and not e.predicted for m, e, _, _ in intake)
        assert not any(m == 'off' for m, _, _, _ in intake)
    finally:
        analyser.stop()


def test_previous_schema_migration_writes_defaults_and_rejects_runtime(tmp_path):
    data = empty_config()
    data['schema_version'] = 2
    data['couplings'] = [Coupling(id='c').to_dict()]
    data['energy_profiles'] = [EnergyProfile(id='e').to_dict()]
    del data['couplings'][0]['beat_accent_mode']
    for field in ('agc_max_gain', 'tracker_gain_floor'):
        del data['energy_profiles'][0][field]
    path = tmp_path/'config.json'
    original = json.dumps(data).encode()
    path.write_bytes(original)
    with pytest.raises(ValueError, match='Unsupported persisted schema'):
        Storage(path)
    assert migrate_file(path, check=True)
    assert path.read_bytes() == original
    assert migrate_file(path)
    current = json.loads(path.read_bytes())
    assert current['schema_version'] == SCHEMA_VERSION == 4
    assert current['couplings'][0]['beat_accent_mode'] == 'onset'
    assert current['energy_profiles'][0]['agc_max_gain'] == 64.
    assert current['energy_profiles'][0]['tracker_gain_floor'] == .3
    assert list(tmp_path.glob('*.bak'))[0].read_bytes() == original
    assert not migrate_file(path)
    assert Storage(path).get_coupling('c').beat_accent_mode == 'onset'
    broken = copy.deepcopy(current)
    del broken['couplings'][0]['beat_accent_mode']
    with pytest.raises(ValueError, match='missing accent settings'):
        validate_current(broken)
    with pytest.raises(ValueError, match='missing accent settings'):
        convert(broken)


def test_gain_ceiling_and_monotone_floor():
    assert [gain_progress(g, 64) for g in (1, 4, 8)] == [0., 0., 0.]
    mapped = [gain_progress(g, 64) for g in range(1, 100)]
    assert mapped == sorted(mapped) and mapped[-1] == 1
    trigger = EnergyTrigger()
    assert all(trigger.process(1e-5 if n % 20 == 0 else 0., n*.01, 'bass') is None
               for n in range(2000))
    assert trigger.gain == 64
    trigger.max_gain = 32
    trigger.process(0, 21., 'bass')
    assert trigger.gain == 32
    # Gain changes no longer change admission of the same Onset candidates.
    raw = event()
    results = []
    for gain in (8.,64.):
        gate = RelativeOnsetGate()
        gate.accepts(replace(raw, id=("test", "warm", 0), candidate_sample=0,
                             strength_raw=.01), .01)
        record = SimpleNamespace(sample_pos=0, features=features(
            diagnostic_events=(raw,), agc_gain=gain))
        results.append(select_events('onset', [], [record], gate=gate))
    assert results[0] == results[1] and results[0]


@pytest.mark.parametrize('values', [{'agc_max_gain':7}, {'agc_max_gain':float('inf')},
                                    {'tracker_gain_floor':-1}, {'tracker_gain_floor':1.1}])
def test_invalid_gain_settings(values):
    with pytest.raises(ValueError):
        EnergyProfile(**values)


def test_real_quiet_noise_cannot_bypass_gain_floor():
    import numpy as np

    from lampastream.canonicalizer import AnalysisPcmFrame

    profile = Profile()
    pipeline = _make_canonical_pipeline(None, profile)
    rng = np.random.default_rng(1401)
    pcm = rng.normal(0, .003, (48000*3, 2)).astype(np.float32)
    records = []
    try:
        for start in range(0, len(pcm), 480):
            samples = pcm[start:start+480]
            samples.setflags(write=False)
            records.extend(pipeline.feed(AnalysisPcmFrame(samples, start, 'quiet', 'offline',
                                                          False, start/48000)))
        records.extend(pipeline.end_of_stream())
        ungated = [e for r in records for e in r.features.diagnostic_events]
        assert ungated  # prove actual picker events existed before the extra floor
        assert max(r.features.agc_gain for r in records) == 64.
        assert select_events('onset', [], records) == []
    finally:
        pipeline.stop()


def test_gain_settings_reach_first_frame_and_change_live():
    import numpy as np

    from lampastream.canonicalizer import AnalysisPcmFrame

    profile = Profile(agc_max_gain=16., tracker_gain_floor=.11)
    pipeline = _make_canonical_pipeline(None, profile)
    engine = SyncEngine(None, profile, analyser=pipeline)
    samples = np.zeros((4800, 2), dtype=np.float32)
    samples.setflags(write=False)
    try:
        assert pipeline._beat_fusion.gain_settings == (16., .11)
        pipeline.feed(AnalysisPcmFrame(samples, 0, 'gain', 'offline', False))
        assert pipeline._beat_fusion.trigger.primary.gain == 16.
        engine.update_render(replace(profile, agc_max_gain=32., tracker_gain_floor=.22))
        assert engine._analyser is pipeline
        assert pipeline._beat_fusion.gain_settings == (32., .22)
        pipeline.feed(AnalysisPcmFrame(samples, 4800, 'gain', 'offline', False))
        assert pipeline._beat_fusion.trigger.primary.gain == 32.
    finally:
        pipeline.stop()
