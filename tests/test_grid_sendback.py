"""Field regressions: reuse notifications, bounded lookups, head grids and handover."""
import asyncio
import logging
import time
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf
from fake_lms_library import Session
from test_grid import clicks, grid

from lampastream.grid import TrackGrid
from lampastream.grid.analyser import analyse_head
from lampastream.grid.cache import GridCache
from lampastream.grid.prior import GridPrior
from lampastream.lms_follower import LmsFollower
from lampastream.lms_grid import LmsGridAdapter, fetch_head, identity
from lampastream.lms_status import _parse_status
from lampastream.track_position import LmsTrackPositionSource


async def until(predicate, timeout=120):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


@pytest.mark.serial
def test_queue_append_mid_play_reuses_listen_feed_and_is_cached_before_change(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    first, second = tmp_path/'a.flac', tmp_path/'b.flac'
    first.write_bytes(clicks())
    audio, rate = sf.read(first)
    sf.write(first, np.tile(audio, 4), rate, format='FLAC')
    second.write_bytes(clicks(period=1.))

    class Observer(LmsFollower):
        _MIRRORS_PLAYBACK = False

    async def run():
        async with Session(first, duration=64) as session:
            adapter = LmsGridAdapter('127.0.0.1', session.web_port, GridCache(tmp_path/'cache'))
            follower = Observer('127.0.0.1', 'aa', 'bb', session.cli_port)
            source = LmsTrackPositionSource('127.0.0.1', lambda: 'aa', session.cli_port,
                                            grid_adapter=adapter)
            source.follow_playlist(follower)
            follower_task = follower.start()
            source.open()
            started = time.monotonic()
            try:
                await until(lambda: session.listeners and source.read())
                await until(lambda: any('no next track' in r.message for r in caplog.records))
                await asyncio.sleep(max(0, 2-(time.monotonic()-started)))
                await session.append(second)
                await until(lambda: any('/music/44437/download' in r for r in session.requests))
                requested = time.monotonic()-started
                assert requested < 64
                await until(lambda: adapter.cache.get(identity('44437', second.stat().st_size)))
                before = len(session.requests)
                session.current_id = '44437'
                session.duration = 16
                status = _parse_status('mode:play time:0 playlist_cur_index:1 '
                                       f'id:44437 filesize:{second.stat().st_size} duration:16')
                source.seed('aa', status, time.monotonic())
                await until(lambda: adapter.state == 'ready')
                assert adapter.cache_state == 'hit' and len(session.requests) == before
                assert session.commands.count('listen 1') == 1
                assert sum('subscribe:10' in c for c in session.commands) == 1
                print(f'B requested at {requested:.3f}s before A ends; B start=hit; '
                      f'fetches unchanged={before}; listen subscriptions=1')
            finally:
                await source.close()
                follower.stop()
                follower_task.cancel()
                await asyncio.gather(follower_task, return_exceptions=True)
        assert any('trigger=playlist-change' in r.message for r in caplog.records)
        assert any('trigger=start' in r.message and 'no next track' in r.message
                   for r in caplog.records)
    asyncio.run(run())


@pytest.mark.serial
def test_periodic_queue_read_is_bounded_and_paused_tracks_do_not_poll(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    path = tmp_path/'a.flac'
    path.write_bytes(clicks())

    async def run():
        async with Session(path) as session:
            adapter = LmsGridAdapter('127.0.0.1', session.web_port, GridCache(tmp_path/'cache'))
            source = LmsTrackPositionSource('127.0.0.1', lambda: 'aa', session.cli_port,
                                            grid_adapter=adapter)
            source.open()
            try:
                await until(lambda: source.read() and source._next_task.done())
                before = len(session.commands)
                source._last_lookup_at -= 31
                source._periodic_lookup()
                await source._next_task
                assert len(session.commands) == before+1
                source._periodic_lookup()
                assert len(session.commands) == before+1
                source._snapshot = replace(source._snapshot, playing=False)
                source._last_lookup_at -= 31
                source._periodic_lookup()
                assert len(session.commands) == before+1
            finally:
                await source.close()
        assert any('trigger=periodic' in r.message for r in caplog.records)
    asyncio.run(run())


def test_head_is_provisional_and_never_enters_full_cache(tmp_path):
    result = analyse_head(clicks())
    assert result.provisional and result.timing_basis == 'content-v1'
    assert result.tempo == pytest.approx(120, abs=2)
    assert TrackGrid.from_dict(result.to_dict()) == result
    with pytest.raises(ValueError, match='provisional'):
        GridCache(tmp_path).put('track', result)


def test_full_grid_adopts_on_next_beat_without_duplicate_and_rejects_disagreement(caplog):
    caplog.set_level(logging.INFO)
    prior = GridPrior()
    head = replace(grid(), provisional=True)
    full = replace(grid(), confidence=.99)
    prior.set(('track', head, 0), .1)
    prior.ticks(.5, False)
    prior.set(('track', full, 0), .7)
    assert prior.grid is head and prior.pending_grid is full
    assert prior.ticks(.9, False) == []
    ticks = prior.ticks(1., False)
    assert prior.grid is full and ticks == [(1., .8, 1)]
    assert prior.ticks(1., False) == []
    prior.set(('other', head, 0), .1)
    prior.set(('other', replace(full, tempo=130), 0), .2)
    assert prior.grid is None
    prior.ticks(.22, False)
    assert prior.grid is None
    prior.ticks(.5, False)
    assert prior.grid is not None
    assert any('dropped before full adoption' in r.message for r in caplog.records)


@pytest.mark.serial
def test_range_response_is_original_prefix_and_total_size_checked(tmp_path):
    path = tmp_path/'source.flac'
    path.write_bytes(clicks())

    async def run():
        async with Session(path) as session:
            destination = tmp_path/'head'
            assert await fetch_head(f'http://127.0.0.1:{session.web_port}', '44436',
                                    path.stat().st_size, destination, duration=16)
            assert destination.read_bytes() == path.read_bytes()
            assert session.ranges[0].startswith('bytes=0-')
            with pytest.raises(ValueError, match='Content-Range'):
                await fetch_head(f'http://127.0.0.1:{session.web_port}', '44436',
                                 path.stat().st_size+1, destination, duration=16)
    asyncio.run(run())


@pytest.mark.serial
def test_partial_container_failure_falls_back_to_verified_full_fetch(tmp_path, caplog):
    import hashlib
    caplog.set_level(logging.INFO)
    path = tmp_path/'opaque.m4a'
    path.write_bytes(b'a'*(512*1024))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    async def run():
        async with Session(path) as session:
            adapter = LmsGridAdapter('127.0.0.1', session.web_port, GridCache(tmp_path/'cache'))

            async def analyse_fixture(file, *, head=False):
                if head and file.stat().st_size < path.stat().st_size:
                    raise ValueError('ALAC M4A moov atom not available in prefix')
                return replace(grid(), file_sha256=digest, provisional=head)

            adapter._analyse = analyse_fixture
            adapter.select('44436', path.stat().st_size, duration=600)
            try:
                await asyncio.wait_for(adapter.queue.join(), 5)
                assert adapter.state == 'ready' and not adapter.grid.provisional
                assert [s['stage'] for s in adapter.stages] == ['head-after-full-fetch', 'full']
                assert len(session.requests) == 2 and session.ranges[0] and not session.ranges[1]
                assert any('falling back to full fetch' in r.message for r in caplog.records)
            finally:
                await adapter.close()
    asyncio.run(run())


def test_provisional_expiry_keeps_tempo_fact_but_returns_to_live_source():
    prior = GridPrior()
    head = replace(grid(), provisional=True)
    prior.set(('track', head, 0), .1)
    assert prior.grid
    prior.ticks(20.1, False)
    prior.set(('track', head, 0), 20.2)
    assert prior.grid is None
    assert prior.status(20.2)['grid_tempo'] == 120


def test_wrong_player_notifications_do_not_trigger_queue_lookups():
    follower = LmsFollower('127.0.0.1', 'aa', 'bb')
    calls = []
    unsubscribe = follower.subscribe_playlist(lambda: calls.append('lookup'))
    follower._notify_playlist('cc playlist addtracks count:1')
    follower._notify_playlist('aa playlist pause 1')
    assert calls == []
    follower._notify_playlist('aa playlist addtracks count:1')
    assert calls == ['lookup']
    unsubscribe()
    follower._notify_playlist('aa playlist delete 0')
    assert calls == ['lookup']


@pytest.mark.parametrize('tempo,shift,rejected', [(122.4, 0., False),
                                                  (122.41, 0., True),
                                                  (120, .51, True)])
def test_provisional_continuity_limits(tempo, shift, rejected):
    prior = GridPrior()
    head = replace(grid(), provisional=True)
    full = replace(grid(), tempo=tempo, beats=tuple(b+shift for b in grid().beats), duration=21.)
    prior.set(('track', head, 0.), .1)
    prior.set(('track', full, 0.), .2)
    assert (prior.grid is None) == rejected
