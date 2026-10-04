"""Coherent player-clock ingress; no LMS, audio device, or wall-clock sleeps."""
import logging
import mmap
import struct
from types import SimpleNamespace

import pytest

from lampastream.canonicalizer import DataResult, StreamInvalidated, TemporarilyNoData
from lampastream.lms_timing import LmsTimedSource
from lampastream.models import VirtualPlayer
from lampastream.pcm_source import SqueezeliteShmStereoSource
from lampastream.player_clock import (
    DISCONTINUITY,
    FLUSH,
    SYNC_PAUSE,
    SYNC_SKIP,
    TIMING_FORMAT,
    TIMING_OFFSET,
    TIMING_SIZE,
)


class Writer:
    def __init__(self, path, timing=True):
        self.path, self.enabled = path, timing
        self.file = path.open('w+b')
        self.file.truncate(TIMING_OFFSET + TIMING_SIZE if timing else TIMING_OFFSET)
        self.mm = mmap.mmap(self.file.fileno(), 0)
        self.pos = self.seq = self.event_seq = self.flags = self.event_frame = self.value = 0
        self.rate, self.generation, self.running = 48000, 1, True
        self.origin = 100.0
        self.anchor = 0
        self.stamp = self.origin
        self.publish()

    def publish(self):
        self.seq += 2
        struct.pack_into('<I', self.mm, 32856, self.seq - 1)
        struct.pack_into('<IIB3xIq', self.mm, 56, 16384, self.pos * 2 % 16384,
                         self.running, self.rate, 1)
        struct.pack_into('<IHHIQQQ4x', self.mm, 32848, 0x48555345, 1,
                         int(self.enabled), self.seq - 1, self.generation, self.pos, 0)
        if self.enabled:
            TIMING_FORMAT.pack_into(self.mm, TIMING_OFFSET, b'YNPT', 1,
                                    self.anchor, round(self.stamp * 1e9), self.rate * 1000,
                                    self.event_seq, self.flags, self.event_frame, self.value)
        struct.pack_into('<I', self.mm, 32856, self.seq)

    def write(self, count=240):
        self.anchor = self.pos
        self.stamp = self.origin + self.pos / self.rate
        for frame in range(self.pos, self.pos + count):
            struct.pack_into('<hh', self.mm, 80 + frame % 8192 * 4, 100, -100)
        self.pos += count
        self.running = True
        self.publish()

    def event(self, flags, value=0):
        self.event_seq += 1
        self.flags, self.value, self.event_frame = flags, value, self.pos
        if flags & SYNC_PAUSE:
            self.running = False
            self.origin += value / 1e9
        if flags & FLUSH:
            self.running = False
        self.publish()

    def close(self):
        self.mm.close()
        self.file.close()


@pytest.fixture
def ingress(tmp_path):
    writer = Writer(tmp_path / 'shm')
    source = SqueezeliteShmStereoSource()
    source.open('aa', _path=writer.path)
    now = [100.0]
    track = SimpleNamespace(title='Song', artist='Artist', playing=True, position_s=0)
    timed = LmsTimedSource(source, VirtualPlayer(head_start_ms=500,
                          speaker_output_delay_ms=30), lambda: track, lambda: now[0])
    yield writer, timed, now, track
    source.close()
    writer.close()


def test_exact_player_stamps(ingress):
    writer, timed, now, _ = ingress
    for i in range(12000):  # 60 simulated seconds, not a fitted read clock
        now[0] = 100 + i * .005 + .004
        writer.write()
        result = timed.read()
        assert isinstance(result, DataResult)
        expected = 100.53 + result.frame.source_sample_pos / writer.rate
        assert abs(result.frame.play_monotonic - expected) < .0005
    assert timed.provenance == 'player clock'
    assert timed.fit.offset is None and not timed.fit.samples


def test_sync_events_do_not_reset_and_pause_shifts_stamps(ingress, caplog):
    writer, timed, now, _ = ingress
    caplog.set_level(logging.INFO)
    writer.write()
    first = timed.read().frame
    epoch = timed.timing.tap_generation
    writer.event(SYNC_PAUSE, 30_000_000)
    assert isinstance(timed.read(), TemporarilyNoData)
    assert timed.fit.generation == 0
    now[0] += .03
    writer.write()
    after = timed.read().frame
    assert after.play_monotonic - first.play_monotonic == pytest.approx(.035, abs=.000001)
    writer.event(SYNC_SKIP, 960)  # 20 ms at 48 kHz, not exported as invented PCM
    assert isinstance(timed.read(), TemporarilyNoData)
    writer.write()
    skipped = timed.read().frame
    assert skipped.play_monotonic - after.play_monotonic == pytest.approx(.005)
    assert timed.timing.tap_generation == epoch  # downstream DSP sees no invalidation
    assert 'SYNC_PAUSE value=30000000 frame=240' in caplog.text
    assert 'SYNC_SKIP value=960 frame=480' in caplog.text


def test_unread_audio_split_at_sync_pause(ingress):
    writer, timed, _, _ = ingress
    writer.write()
    timed.read()
    writer.write()  # unread pre-pause samples
    writer.event(SYNC_PAUSE, 30_000_000)
    writer.write()  # unread post-pause samples
    before, after = timed.read(), timed.read()
    assert isinstance(before, DataResult) and isinstance(after, DataResult)
    assert len(before.frame.samples) == len(after.frame.samples) == 240
    assert before.frame.play_monotonic == pytest.approx(100.535)
    assert after.frame.play_monotonic == pytest.approx(100.57)


@pytest.mark.parametrize('event', [FLUSH, DISCONTINUITY])
def test_real_boundary_invalidates_once(ingress, event, caplog):
    writer, timed, _, track = ingress
    caplog.set_level(logging.INFO)
    writer.write()
    timed.read()
    old = timed.timing.tap_generation
    writer.event(event)
    writer.write()
    assert isinstance(timed.read(), StreamInvalidated)
    # Metadata can follow the authoritative PCM boundary; never reset twice.
    track.title = 'Next'
    track.position_s = 0
    assert isinstance(timed.read(), DataResult)
    assert isinstance(timed.read(), TemporarilyNoData)
    assert timed.timing.tap_generation == old + 1
    assert caplog.text.count('LMS stream invalidated:') == 1


def test_old_player_fallback(tmp_path):
    writer = Writer(tmp_path / 'old', timing=False)
    source = SqueezeliteShmStereoSource()
    source.open('aa', _path=writer.path)
    now = [100.0]
    timed = LmsTimedSource(source, VirtualPlayer(), clock=lambda: now[0])
    try:
        timed.read()
        for _i in range(1, 100):
            now[0] += .005
            writer.write()
            result = timed.read()
        assert isinstance(result, DataResult)
        assert result.frame.play_monotonic is not None
        assert timed.provenance == 'write-clock estimate'
        assert timed.fit.offset is not None
    finally:
        source.close()
        writer.close()


@pytest.mark.parametrize('bad', ['magic', 'version', 'rate', 'flag'])
def test_invalid_optional_block_falls_back(ingress, bad):
    writer, timed, _, _ = ingress
    if bad == 'magic':
        writer.mm[TIMING_OFFSET:TIMING_OFFSET + 4] = b'BAD!'
    elif bad == 'version':
        struct.pack_into('<H', writer.mm, TIMING_OFFSET + 4, 2)
    elif bad == 'rate':
        struct.pack_into('<I', writer.mm, TIMING_OFFSET + 24, 0)
    else:
        struct.pack_into('<H', writer.mm, 32854, 0)
    timed.read()
    assert timed.provenance == 'write-clock estimate'


def test_follow_reader_keeps_legacy_semantics(ingress):
    writer, timed, _, _ = ingress
    timed.source.use_player_clock = False
    writer.write()
    frame = timed.source.read().frame
    assert frame.play_monotonic is None
    writer.event(SYNC_PAUSE, 30_000_000)
    assert isinstance(timed.source.read(), TemporarilyNoData)
    writer.write()
    assert isinstance(timed.source.read(), StreamInvalidated)  # original running-edge rule


def test_sync_corrections_keep_canonical_dsp_epoch(ingress):
    from lampastream.canonicalizer import AudioCanonicalizer, CanonicalData
    writer, timed, _, _ = ingress
    canonicalizer = AudioCanonicalizer(quality='LQ')
    epochs = set()
    for i in range(120):
        if i == 40:
            writer.event(SYNC_PAUSE, 30_000_000)
            canonicalizer.push(timed.read())
        if i == 80:
            writer.event(SYNC_SKIP, 960)
            canonicalizer.push(timed.read())
        writer.write()
        result = timed.read()
        assert not isinstance(result, StreamInvalidated)
        for output in canonicalizer.push(result):
            if isinstance(output, CanonicalData):
                epochs.add(output.frame.epoch_id)
    assert len(epochs) == 1


@pytest.mark.parametrize('change', ['rate', 'generation'])
def test_clock_real_changes_invalidate_once(ingress, change):
    writer, timed, _, _ = ingress
    writer.write()
    timed.read()
    if change == 'rate':
        writer.rate = 44100
        writer.event(DISCONTINUITY)
    else:
        writer.generation += 1
    writer.write()
    assert isinstance(timed.read(), StreamInvalidated)
    writer.write()
    assert isinstance(timed.read(), DataResult)


@pytest.mark.parametrize('provenance', ['player clock', 'write-clock estimate'])
def test_status_publishes_clock_provenance(ingress, tmp_path, provenance):
    from lampastream.models import Coupling, Profile, VirtualPlayerType
    from lampastream.player_manager import ActiveSession, PlayerManager
    from lampastream.storage import Storage
    _, timed, _, _ = ingress
    timed.provenance = provenance
    timed.player.follow_mode = "sync_group"
    storage = Storage(tmp_path / 'config.json')
    storage.save_virtual_player(timed.player)
    manager = PlayerManager(storage)
    manager._active = ActiveSession(Profile(), coupling=Coupling(player_id=timed.player.id),
                                    player_type=VirtualPlayerType.LMS)
    manager._active.lms_timed_source = timed
    status = manager.lms_timing  # forwarded unchanged by /api/status and websocket status
    assert status['provenance'] == provenance
    assert status['audio_source'] == 'LMS head start'
