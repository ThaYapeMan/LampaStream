"""Owner journal ordering: buffered prgr precedes DMAP mper/astm title batches."""
import base64

from lampastream.track_position import AirPlayTrackPositionSource


def wire(code, data=b'', kind='ssnc'):
    if isinstance(data, str):
        data = data.encode()
    return (f'<item><type>{kind.encode().hex()}</type><code>{code.encode().hex()}</code>'
            f'<length>{len(data)}</length><data>{base64.b64encode(data).decode()}</data>'
            '</item>').encode()


def metadata(identity=1, title='Track', duration=381000):
    return (wire('mdst', '2352532984') + wire('mper', identity.to_bytes(8, 'big'), 'core')+
        wire('minm', title, 'core') + wire('astm', duration.to_bytes(4, 'big'), 'core')+
        wire('mden', '2352532984'))


def test_progress_before_first_metadata_batch_survives(monkeypatch):
    monkeypatch.setattr('lampastream.track_position.time.monotonic', lambda: 100.)
    source = AirPlayTrackPositionSource()
    source.feed(wire('pbeg')+wire('pres')+wire('prgr', '100000/541000/16902100'))
    source.feed(metadata())
    status = source.read().for_delivery()
    assert status['position_s'] == 10.
    assert status['duration_s'] == 381.
    assert status['playing']


def test_buffered_preroll_progress_then_metadata_and_heartbeat(monkeypatch):
    now = [100.]
    monkeypatch.setattr('lampastream.track_position.time.monotonic', lambda: now[0])
    source = AirPlayTrackPositionSource()
    start = 2352532984
    # Real journal order and types; numeric payloads are representative because
    # the journal logs prgr lengths, not its three RTP values. Buffered playback
    # can report a current RTP coordinate before the track start becomes audible.
    source.feed(wire('pbeg')+wire('pres')+
        wire('prgr', f'{start}/{start-44100}/{start+381*44100}')+metadata())
    assert source.read().for_delivery()['duration_s'] == 381.
    assert source.read().for_delivery()['position_s'] == 0.
    now[0] = 100.5
    source.feed(metadata())  # title refresh must not start a future anchor early
    assert source.read().position_now() == 0.
    now[0] = 102.
    assert source.read().position_now() == 1.
    source.feed(wire('phbt', f'{start+90*44100}/123456789'))
    assert source.read().position_now() == 90.
    source.feed(wire('paus'))
    now[0] += 3
    assert source.read().position_now() == 90.
    source.feed(wire('pend'))
    assert source.read() is None


def test_dmap_duration_and_persistent_identity_do_not_retain_stale_progress(monkeypatch):
    monkeypatch.setattr('lampastream.track_position.time.monotonic', lambda: 100.)
    source = AirPlayTrackPositionSource()
    source.feed(wire('pbeg')+wire('prgr', '0/441000/16802100')+metadata())
    assert source.read().position_now() == 10.
    source.feed(metadata(identity=2, title='Track', duration=200000))
    assert source.read().duration_s == 200.
    assert source.read().position_s is None
    # An unknown track origin must not be fabricated from wall time or PCM age.
    source.feed(wire('phbt', '441000/12345'))
    assert source.read().position_s is None
