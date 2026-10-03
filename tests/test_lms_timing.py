"""LMS timing tests: no receiver, bridge, or real LMS connection."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from lampastream.api import VirtualPlayerCreateBody, VirtualPlayerPatchBody
from lampastream.lms_timing import WriteClock, configure_head_start
from lampastream.migration import convert
from lampastream.models import VirtualPlayer
from lampastream.schema import empty_config


def test_pref_is_verified_and_start_delay_is_never_written(caplog):
    exchange = Mock(side_effect=['ok', 'aa playerpref playDelay 500',
                                 'aa playerpref startDelay 20'])
    player = VirtualPlayer(player_mac='aa', follow_mode='sync_group')
    assert configure_head_start(player, exchange)
    assert [call.args[2] for call in exchange.call_args_list] == [
        'aa playerpref playDelay 500\n', 'aa playerpref playDelay ?\n',
        'aa playerpref startDelay ?\n']
    assert 'leave it unchanged' in caplog.text
    assert all(call.args[0] == player.lms_host for call in exchange.call_args_list)


def test_follow_does_not_change_any_preferences():
    exchange = Mock()
    assert not configure_head_start(VirtualPlayer(), exchange)
    exchange.assert_not_called()


def test_preference_mismatch_refuses_timed_mode():
    with pytest.raises(ValueError, match='verify'):
        configure_head_start(VirtualPlayer(player_mac='aa', follow_mode='sync_group'),
                             Mock(side_effect=['ok', 'aa playerpref playDelay 0']))


@pytest.mark.parametrize('rate', [44100, 48000])
@pytest.mark.parametrize('drift', [-.0005, 0, .0005])
def test_bracket_fit_with_jitter_and_late_reads(rate, drift):
    rng = np.random.default_rng(21)
    fit = WriteClock()
    now = 100.0
    errors = []
    actual_rate = rate * (1 + drift)
    for i in range(6000):
        now += .005 + rng.uniform(-.002, .002)
        if i % 317 == 0:
            now += .030  # late reader polls must not create timing epochs
        writer_time = np.floor((now - 100) / .010) * .010
        pos = round(writer_time * actual_rate)
        changed = fit.observe(pos, now - .00001, now, rate, 1, 0, True)
        assert not changed
        if fit.offset is not None and now > 106:
            errors.append(abs(fit.at(pos) - (100 + pos / actual_rate)) * 1000)
    assert np.percentile(errors, 95) <= 2


@pytest.mark.parametrize('kind', ['skip', 'pause', 'generation', 'gap'])
def test_discontinuities_start_new_epochs(kind):
    fit = WriteClock()
    for i in range(100):
        fit.observe(i * 441, i * .01, i * .01 + .001, 44100, 1, 0, True)
    generation = fit.generation
    if kind == 'skip':
        changed = fit.observe(110 * 441, 1, 1.001, 44100, 1, 0, True)
    elif kind == 'pause':
        changed = fit.observe(99 * 441, 1.04, 1.041, 44100, 1, 0, True)
    else:
        changed = fit.observe(100 * 441, 1, 1.001, 44100,
                              2 if kind == 'generation' else 1, int(kind == 'gap'), True)
    assert changed
    assert fit.generation > generation


@pytest.mark.parametrize('field,value', [('head_start_ms', -1), ('head_start_ms', 2001),
                                        ('head_start_ms', 1.5), ('head_start_ms', True),
                                        ('speaker_output_delay_ms', -201),
                                        ('speaker_output_delay_ms', 501)])
def test_settings_reject_invalid_values(field, value):
    with pytest.raises(ValueError):
        VirtualPlayer(**{field: value})
    for model in [VirtualPlayerCreateBody, VirtualPlayerPatchBody]:
        with pytest.raises(ValueError):
            model(**{field: value})


def test_migration_preserves_explicit_values_and_adds_defaults():
    original = empty_config()
    original['virtual_players'] = [VirtualPlayer().to_dict(), VirtualPlayer().to_dict()]
    original['virtual_players'][0].pop('head_start_ms')
    original['virtual_players'][0].pop('speaker_output_delay_ms')
    original['virtual_players'][1].update(head_start_ms=0, speaker_output_delay_ms=-50)
    data = convert(original)
    assert data['virtual_players'][0]['head_start_ms'] == 500
    assert data['virtual_players'][0]['speaker_output_delay_ms'] == 0
    assert data['virtual_players'][1]['head_start_ms'] == 0
    assert data['virtual_players'][1]['speaker_output_delay_ms'] == -50
    assert convert(data) == data


class PacedSource:
    def __init__(self):
        self._mm = True
        self.position = 0
        self.consumed = 0
        self.generation = 1
        self.gap = 0
        self.running = True

    def _read_ext_coherent(self):
        return SimpleNamespace(abs_write_pos=self.position, generation=self.generation,
                               gap_seq=self.gap)

    def _read_header(self):
        return 10000, 0, self.running, 44100, 0

    def read(self):
        from lampastream.canonicalizer import DataResult, DecodedSourceFrame, TemporarilyNoData
        count = self.position - self.consumed
        if count <= 0:
            return TemporarilyNoData()
        pos = self.consumed
        self.consumed = self.position
        return DataResult(DecodedSourceFrame(np.ones((count, 2), dtype=np.float32) * .1,
                          44100, 2, 'lms:aa', pos, False, None))


def timed_source(head=500, speaker=0):
    from lampastream.lms_timing import LmsTimedSource
    source = PacedSource()
    now = [10.0]
    track = [SimpleNamespace(title='Song', artist='Artist', playing=True)]
    timed = LmsTimedSource(source, VirtualPlayer(head_start_ms=head,
                          speaker_output_delay_ms=speaker), lambda: track[0], lambda: now[0])
    return timed, source, now, track


def poll(timed, source, now, elapsed):
    now[0] = 10 + elapsed
    source.position = int(elapsed / .01) * 441
    return timed.read()


def test_audible_time_and_canonical_publications():
    from pipeline_factory import make_pipeline

    from lampastream.canonicalizer import AudioCanonicalizer, CanonicalData, DataResult
    timed, source, now, _ = timed_source(speaker=30)
    canonicalizer = AudioCanonicalizer(quality='LQ')
    from lampastream.models import Profile
    profile = Profile()
    pipeline = make_pipeline(source=None, **{key: getattr(profile, key) for key in (
        "onset_method", "onset_delta", "onset_alpha", "superflux_mu", "superflux_lag",
        "bass_hz", "mid_hz")})
    rng = np.random.default_rng(9)
    elapsed = 0
    timed.read()
    try:
        for _ in range(250):
            elapsed += .005 + rng.uniform(-.002, .002)
            result = poll(timed, source, now, elapsed)
            if isinstance(result, DataResult) and result.frame.play_monotonic is not None:
                assert result.frame.play_monotonic == pytest.approx(
                    10.53 + result.frame.source_sample_pos / 44100, abs=.003)
            for canonical in canonicalizer.push(result):
                if isinstance(canonical, CanonicalData):
                    pipeline._process_canonical_frame(canonical.frame)
        publications = pipeline.drain_publications()
        stamped = [p for p in publications if p.features.play_monotonic is not None]
        assert len(stamped) > 20
        for p in stamped:
            assert p.features.play_monotonic == pytest.approx(10.53 + p.sample_pos / 48000,
                                                             abs=.003)
            assert p.features.timing_generation == timed.timing.tap_generation
            assert p.features.received_monotonic is not None
    finally:
        pipeline.stop()


@pytest.mark.parametrize('kind', ['track', 'pause', 'generation', 'gap'])
def test_ingress_discontinuity_discards_current_pcm(kind):
    from lampastream.canonicalizer import StreamInvalidated
    timed, source, now, track = timed_source()
    for i in range(30):
        poll(timed, source, now, i * .005)
    old = timed.timing.tap_generation
    if kind == 'track':
        track[0].title = 'Next'
    elif kind == 'pause':
        track[0].playing = False
    elif kind == 'generation':
        source.generation += 1
    else:
        source.gap += 1
    result = poll(timed, source, now, .15)
    assert isinstance(result, StreamInvalidated)
    assert timed.timing.tap_generation > old


def test_fallback_requires_five_seconds_then_recovers_from_measured_lead():
    timed, source, now, _ = timed_source(head=100)
    elapsed = 0
    for i in range(650):
        elapsed += .01
        timed.timing.processing_window.samples.append((90, i))
        poll(timed, source, now, elapsed)
        if i < 490:
            assert timed.timing.tap_source == 'LMS head start'
    assert timed.timing.tap_source == 'delay fallback'
    assert timed.reason == 'Not enough head start, using delay instead'
    timed.player.head_start_ms = 500
    for i in range(1200):
        elapsed += .01
        timed.timing.processing_window.samples.append((90, i))
        poll(timed, source, now, elapsed)
    assert timed.timing.tap_source == 'LMS head start'
    assert timed.reason is None


def test_timed_output_renders_every_publication_without_latest_sampling(monkeypatch):
    import asyncio
    from dataclasses import replace

    from lampastream.latency import NoLatencyProbe
    from lampastream.lms_timing import LmsTimingDiagnostics
    from lampastream.models import Profile
    from lampastream.sync_engine import CanonicalAnalysisPipeline, SyncEngine
    from lampastream.types import AudioFeatures
    now = [10.1]
    features = AudioFeatures(bars=[.2] * 30, bass=.2, mid=.2, full=.2, centroid=.2,
                             onset=False, onset_strength=0, received_monotonic=10,
                             play_monotonic=10.5, timing_generation=1)
    records = [SimpleNamespace(features=replace(features, onset=i == 1)) for i in range(3)]

    class Pipeline(CanonicalAnalysisPipeline):
        def __init__(self):
            self.records = records

        def drain_publications(self):
            result, self.records = self.records, []
            return result

        def latest(self):
            raise AssertionError('Timed sources must not sample latest()')

    diagnostics = LmsTimingDiagnostics(clock=lambda: now[0])
    diagnostics.tap_source = 'LMS head start'
    diagnostics.tap_generation = 1
    def render(*args):
        now[0] += .002
        return 'scene'
    effect = SimpleNamespace(render=Mock(side_effect=render), mix=.2)
    engine = SyncEngine(None, Profile(), analyser=Pipeline(), probe=NoLatencyProbe(),
                        timing=diagnostics)
    engine._effect = effect
    output = Mock()
    output.send.side_effect = lambda *args: now.__setitem__(0, now[0] + .001)

    async def sleep(interval):
        now[0] += interval
        if now[0] > 10.6:
            raise asyncio.CancelledError

    monkeypatch.setattr('lampastream.sync_engine.time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr('lampastream.sync_engine.asyncio', SimpleNamespace(sleep=sleep))
    async def run():
        try:
            await engine.run(output)
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
    assert effect.render.call_count == 3
    assert effect.render.call_args_list[1].args[0].onset is True
    output.send.assert_called_once()
    assert output.send.call_args.args[1] >= 10.5

    data = diagnostics.snapshot()
    assert data['median_processing_ms'] > 0
    assert len([e for e in data['events'] if e['kind'] == 'scene-ready']) == 3
    assert data['events'][-1]['sent_monotonic'] >= 10.5


def test_settings_rest_round_trip_and_bounds(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from lampastream.api import router
    from lampastream.storage import Storage
    app = FastAPI()
    app.include_router(router)
    app.state.storage = Storage(tmp_path / 'config.json')
    app.state.player_manager = Mock()
    with TestClient(app) as client:
        created = client.post('/api/virtual-players', json={'head_start_ms': 600,
                              'speaker_output_delay_ms': -100}).json()
        assert created['head_start_ms'] == 600
        url = '/api/virtual-players/' + created['id']
        updated = client.patch(url, json={'head_start_ms': 0,
                               'speaker_output_delay_ms': 500}).json()
        assert updated['head_start_ms'] == 0
        assert updated['speaker_output_delay_ms'] == 500
        assert app.state.storage.get_virtual_player(created['id']).head_start_ms == 0
        assert client.patch(url, json={'head_start_ms': 2001}).status_code == 422
        assert client.patch(url, json={'speaker_output_delay_ms': None}).status_code == 422


def test_zero_explicitly_clears_the_previous_head_start():
    exchange = Mock(side_effect=['ok', 'aa playerpref playDelay 0',
                                 'aa playerpref startDelay 0'])
    assert configure_head_start(VirtualPlayer(player_mac='aa', follow_mode='sync_group',
                                head_start_ms=0), exchange)
    assert exchange.call_args_list[0].args[2] == 'aa playerpref playDelay 0\n'


def test_large_export_batches_are_not_mistaken_for_pauses():
    fit = WriteClock()
    for i in range(500):
        now = i * .005
        pos = int(now / .04) * 1764
        changed = fit.observe(pos, now, now + .0001, 44100, 1, 0, True)
        assert not changed


def test_status_uses_measured_scheduled_hold_and_legacy_when_off(tmp_path):
    from lampastream.airplay_timing import TimingDiagnostics
    from lampastream.latency import FixedLatencyProbe
    from lampastream.models import Coupling, PlayerLatency, Profile, VirtualPlayerType
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    storage = Storage(tmp_path / 'config.json')
    player = VirtualPlayer(player_mac='virtual', follow_mode='sync_group')
    storage.save_virtual_player(player)
    manager = PlayerManager(storage)
    session = ActiveSession(Profile(), coupling=Coupling(player_id=player.id),
                            player_type=VirtualPlayerType.LMS)
    config = PlayerLatency(player_mac='speaker', strategy='fixed', fixed_delay_ms=90,
                           trim_ms=-10)
    session.probe = FixedLatencyProbe(90)
    session.probe.config = config
    session.latency_mac = 'speaker'
    diagnostics = TimingDiagnostics(clock=lambda: 1.5)
    diagnostics.tap_source = 'LMS head start'
    diagnostics.tap_arrival(.486, 0)
    diagnostics.arrival(441, 1)
    diagnostics.processing(1, 1.019, 1.5)
    session.lms_timed_source = SimpleNamespace(timing=diagnostics, reason=None, ready=True,
                                                fit_snapshot=dict(precision_ms=1.5,
                                                                  sample_count=100,
                                                                  samples=[],
                                                                  last_sample_time=123),
                                                readiness_state="scheduled")
    manager._active = session
    assert manager.lms_timing['state'] == 'scheduled'
    assert manager.lms_timing['sample_count'] == 100
    assert manager.lms_timing['precision_ms'] == 1.5
    assert manager.lms_timing['lead_p5_ms'] == 486
    assert manager.lms_timing['median_processing_ms'] == pytest.approx(19)
    assert manager.applied_delay_ms == 457
    assert manager.latency_status(config)['audio_source'] == 'LMS head start'
    session.lms_timed_source = None
    player.head_start_ms = 0
    storage.save_virtual_player(player)
    assert manager.lms_timing['state'] == 'off'
    assert manager.applied_delay_ms == session.probe.current_delay_ms()


@pytest.mark.parametrize('timed', [True, False])
def test_probe_exposes_trim_only_for_timed_lms(tmp_path, timed):
    import asyncio

    from lampastream.models import PlayerLatency, Profile
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage

    storage = Storage(tmp_path / 'config.json')
    config = PlayerLatency(player_mac='speaker', strategy='fixed', fixed_delay_ms=90,
                           trim_ms=-10)
    storage.save_player_latency(config)
    manager = PlayerManager(storage)
    session = ActiveSession(Profile(player_mac='virtual'))
    session.lms_timed_source = object() if timed else None
    asyncio.run(manager._apply_probe_for_master(session, 'speaker'))
    assert session.probe.current_delay_ms() == 90
    assert getattr(session.probe, 'config', None) == (config if timed else None)


def test_readiness_gate_keeps_pcm_untimed_and_invalidates_when_ready():
    from lampastream.airplay_timing import percentile
    from lampastream.canonicalizer import DataResult, StreamInvalidated

    timed, source, now, _ = timed_source()
    for i in range(30):
        poll(timed, source, now, i * .005)
    generation = timed.timing.tap_generation
    timed.set_readiness(False, 'waiting', 'Waiting for the virtual player in LMS')
    assert isinstance(poll(timed, source, now, .15), StreamInvalidated)
    result = poll(timed, source, now, .16)
    assert isinstance(result, DataResult) and result.frame.play_monotonic is None
    assert timed.timing.tap_source == 'delay fallback'
    timed.set_readiness(True, 'scheduled', None)
    assert isinstance(poll(timed, source, now, .17), StreamInvalidated)
    result = poll(timed, source, now, .18)
    assert isinstance(result, DataResult) and result.frame.play_monotonic is not None
    assert result.frame.timing_generation > generation
    assert timed.fit_snapshot['sample_count'] == len(timed.fit.samples)
    residuals = [max(lo - timed.fit.at(pos), timed.fit.at(pos) - hi, 0) * 1000
                 for pos, lo, hi in timed.fit.samples]
    assert timed.fit_snapshot['precision_ms'] == percentile(residuals, .95)
    assert timed.fit_snapshot['samples']
