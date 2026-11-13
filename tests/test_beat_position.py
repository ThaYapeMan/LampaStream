"""Canonical musical time, independent of ingress and output adapters."""
from dataclasses import FrozenInstanceError, asdict

import numpy as np
import pytest

from lampastream.beat_fusion import BeatFusion
from lampastream.canonicalizer import AnalysisPcmFrame
from lampastream.grid import Section, TrackGrid
from lampastream.models import Profile
from lampastream.player_manager import _make_canonical_pipeline
from lampastream.types import BeatPosition


def known_grid(meter=4):
    beats = tuple(.25+i*60/128 for i in range(256))
    return TrackGrid('4', 'a'*64, 121., 48000, 128., beats,
                     (True,)*len(beats), (Section('music', 0., 121., bar_length=meter),),
                     .94, 'content-v1')


def timeline(grid=None, identity='track'):
    fusion = BeatFusion()
    fusion.prior.set((identity, grid or known_grid(), 0.), 0.)
    return fusion


def test_reference_rows_and_in_between_frames():
    fusion = timeline()
    grid = fusion.prior.grid
    for n, t in enumerate(grid.beats):
        record = fusion.position(t)
        assert record.beat_index == n
        assert record.bar_index == n//4
        assert record.beat_phase == pytest.approx(0., abs=1e-9)
        assert record.bar_phase == pytest.approx((n % 4)/4)
        assert record.confidence == .5
        assert not record.downbeat_measured
        assert record.source == 'grid'
        if n+1 < len(grid.beats):
            middle = fusion.position((t+grid.beats[n+1])/2)
            assert middle.beat_phase == pytest.approx(.5)
            assert middle.beat_index == n
    with pytest.raises(FrozenInstanceError):
        record.tempo = 120
    print('256 grid reference rows: beat_index=n, bar_index=n//4; midpoints phase=0.5')


def test_three_beat_meter_and_content_origin():
    fusion = timeline(known_grid(3))
    fusion.content_origin = 30.
    record = fusion.position(fusion.prior.grid.beats[17])
    assert (record.beats_per_bar, record.beat_index, record.bar_index) == (3, 17, 5)
    assert record.bar_phase == pytest.approx(2/3)


def test_handover_is_monotonic_bounded_and_counts_raw_jump(caplog):
    fusion = timeline()
    before = fusion.position(fusion.prior.grid.beats[174])
    fusion.prior.grid = None
    fusion.clock.locked = True
    fusion.clock.tempo_bpm = 128.
    fusion.clock.confidence = .9
    fusion.clock.anchor = fusion.prior.available.beats[174]
    fusion.clock.beat_index = 20
    after = fusion.position(fusion.clock.anchor+.01)
    assert before.beat_index <= after.beat_index <= before.beat_index+1
    assert fusion.beat_index_jumps == 1
    assert 'beat_index_jumps=1' in caplog.text
    assert after.source == 'tracker'
    fusion.prior.grid = fusion.prior.available
    back = fusion.position(fusion.clock.anchor+.02)
    assert after.beat_index <= back.beat_index <= after.beat_index+1
    print(f'grid {before.beat_index} → tracker {after.beat_index} → grid {back.beat_index}; '
          f'raw jumps counted={fusion.beat_index_jumps}')


def test_identity_resets_but_analyser_reset_keeps_same_track_count():
    fusion = timeline()
    before = fusion.position(fusion.prior.grid.beats[174])
    fusion.reset()
    fusion.prior.set(('track', known_grid(), 0.), 0.)
    assert fusion.position(82.).beat_index >= before.beat_index
    fusion.prior.set(('different', known_grid(), 0.), 0.)
    assert fusion.position(.25).beat_index == 0


def test_onset_zero_record_even_with_a_grid_or_tracker():
    fusion = timeline()
    fusion.accent_mode = 'onset'
    assert fusion.position(60.) == BeatPosition()
    assert asdict(fusion.position(60.)) == dict(
        tempo=None, beat_phase=0., beat_index=0, bar_phase=0., bar_index=0,
        confidence=0., source='onset', beats_per_bar=4, downbeat_measured=False)


def test_prediction_lookup_cannot_advance_current_frame_count():
    fusion = timeline()
    fusion.position(5.)
    previous = fusion.position_last
    fusion.position(100., advance=False)
    assert fusion.position_last == previous
    assert fusion.position(5.01).beat_index == previous[1]


def test_every_publication_uses_content_clock_and_matches_legacy_scalars():
    grid = known_grid()
    pipeline = _make_canonical_pipeline(None, Profile(
        bars_source='pcm_pipeline', spectrum_backend='v2', beat_accent_mode='tracker'))
    pipeline._beat_fusion.grid_provider = lambda frame: ('track', grid, 30., {})
    records = []
    try:
        for start in range(0, 9600, 480):
            frame = AnalysisPcmFrame(np.zeros((480, 2), dtype=np.float32), start,
                                     'epoch', 'test', False,
                                     content_position_s=30.+start/48000)
            records.extend(pipeline.feed(frame))
        assert records
        for record in records:
            features = record.features
            position = features.beat_position
            assert position.beat_index == int((30.+record.sample_pos/48000-.25)/(60/128))
            assert features.tempo_bpm == position.tempo
            assert features.beat_phase == position.beat_phase
            assert features.tempo_confidence == position.confidence
            assert features.grid_tempo == position.tempo
            assert features.grid_confidence == position.confidence
    finally:
        pipeline.stop()


def test_logger_exports_the_indices_on_every_accent_row():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1]/'scripts/ab-logger.py'
    spec = importlib.util.spec_from_file_location('position_logger', path)
    logger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(logger)
    event = dict(detected_audible_monotonic=100., kind='beat', id=('track', 'grid', 0),
                 beat_source='grid', beat_index=174, bar_index=43)
    rows = list(logger.beat_rows(event, 1000., 'tracker', True))
    assert rows
    assert all(row['beat_index'] == 174 and row['bar_index'] == 43 for row in rows)
    assert 'beat_index' in logger.BEAT_FIELDS and 'bar_index' in logger.BEAT_FIELDS


def test_private_mau_p_reference_rows():
    import csv
    import os
    from pathlib import Path

    value = os.environ.get('LAMPASTREAM_BEAT_POSITION_REFERENCE')
    if not value:
        pytest.skip('Set LAMPASTREAM_BEAT_POSITION_REFERENCE to the private Mau P beats.csv')
    with Path(value).open() as stream:
        rows = list(csv.DictReader(stream))
    beats = tuple(float(row['time_s']) for row in rows)
    grid = TrackGrid('4', 'b'*64, beats[-1]+1., 48000, 127.998, beats,
                     (True,)*len(beats), (), .94, 'content-v1')
    fusion = timeline(grid)
    for row in rows:
        n = int(row['beat'])
        position = fusion.position(float(row['time_s']))
        assert position.beat_index == n
        assert position.bar_index == n//4
    print(f'Mau P reference grid: {len(rows)} rows; beat_index=n, bar_index=n//4')


def test_seek_epoch_does_not_rewind_the_same_identity_counter():
    fusion = timeline()
    first = fusion.position(80., epoch='first')
    fusion.reset()
    fusion.prior.set(('track', known_grid(), 0.), 0.)
    next_playback = fusion.position(20., epoch='seek')
    assert next_playback.beat_index >= first.beat_index
    assert fusion.position(20.5, epoch='seek').beat_index > next_playback.beat_index


def test_republishing_analysed_features_cannot_reestimate_the_position():
    pipeline = _make_canonical_pipeline(None, Profile(bars_source='pcm_pipeline'))
    try:
        position = BeatPosition(128., .63, 174, .16, 43, .5, 'grid', 4, False)
        from lampastream.types import AudioFeatures
        features = AudioFeatures([], 0, 0, 0, 0, beat_position=position,
                                 tempo_bpm=128., beat_phase=.63, tempo_confidence=.5)
        pipeline._beat_fusion.reset()
        record = pipeline._publish(epoch_id='replay', sample_start=0, sample_end=480,
                                   features=features, effective_spectrum_backend='v2',
                                   effective_processor_ids=())
        assert record.features.beat_position is position
        assert record.features.tempo_bpm == position.tempo
    finally:
        pipeline.stop()
