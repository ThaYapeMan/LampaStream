"""AIRPLAY-02: metadata-owned DACP identity and bounded sender control."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lampastream.airplay_transport import DacpTransport
from lampastream.models import Profile, VirtualPlayer, VirtualPlayerType
from lampastream.player_manager import ActiveSession, PlayerManager
from lampastream.storage import Storage
from lampastream.track_position import AirPlayTrackPositionSource


def test_dacp_commands_headers_expiry_and_disappearance():
    async def run():
        requests = []
        async def sender(reader, writer):
            data = (await reader.readuntil(b'\r\n\r\n')).decode()
            requests.append(data)
            writer.write(b'HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(sender, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        resolver = AsyncMock(return_value=('127.0.0.1', port))
        now = [10.]
        client = DacpTransport(resolver, clock=lambda: now[0])
        assert not client.capability['available']
        client.update('daid', 'DEADBEEF')
        client.update('acre', '12345')
        await client.refresh()
        assert client.capability['available']
        for action in ('play', 'pause', 'toggle', 'next', 'previous'):
            assert await client.control(action) == 'DEADBEEF'
        assert [r.split()[1] for r in requests] == [
            '/ctrl-int/1/play', '/ctrl-int/1/pause', '/ctrl-int/1/playpause',
            '/ctrl-int/1/nextitem', '/ctrl-int/1/previtem']
        assert all('Active-Remote: 12345' in r for r in requests)
        with pytest.raises(RuntimeError, match='does not support'):
            await client.control('seek_forward')
        now[0] += 6
        assert not client.capability['available']
        server.close()
        await server.wait_closed()
        with pytest.raises(OSError, match='unavailable'):
            await client.control('play')
        assert not client.capability['available']
        resolver.side_effect = OSError('sender gone')
        await client.refresh()
        assert client.capability['reason'] == 'sender gone'
        client.reset()
        assert client.identifier is client.active_remote is None
    asyncio.run(run())


def test_metadata_identity_is_not_reused_across_senders_or_receiver_restarts():
    source = AirPlayTrackPositionSource('/tmp/unused-metadata-test')
    source._item('ssnc', 'daid', 'AABB')
    source._item('ssnc', 'acre', '42')
    source.transport.endpoint = ('127.0.0.1', 1234)
    source.transport.expires = float('inf')
    assert source.transport.capability['available']
    source._item('ssnc', 'daid', 'CCDD')
    assert not source.transport.capability['available']
    source._item('ssnc', 'acre', 'bad\r\nheader')
    assert source.transport.active_remote is None
    source.invalidate()
    assert source.transport.identifier is None


def test_both_players_expose_the_generic_capability(tmp_path):
    manager = PlayerManager(Storage(tmp_path/'config.json'))
    own, room = '02:00:00:00:00:01', '02:00:00:00:00:02'
    manager.storage.save_virtual_player(VirtualPlayer(player_mac=own))
    session = ActiveSession(Profile(player_mac=own))
    session.follower = SimpleNamespace(target_mac=room)
    manager._active = session
    assert manager.transport_capability['available']
    assert manager.transport_capability['target_id'] == room
    session.player_type = VirtualPlayerType.AIRPLAY
    tracks = AirPlayTrackPositionSource('/tmp/unused-metadata-test')
    manager._airplay_tracks = tracks
    assert not manager.transport_capability['available']
    tracks._item('ssnc', 'daid', 'AABB')
    tracks._item('ssnc', 'acre', '42')
    tracks.transport.endpoint, tracks.transport.expires = ('127.0.0.1', 1234), float('inf')
    assert manager.transport_capability['available']
    assert 'seek_forward' not in manager.transport_capability['actions']
