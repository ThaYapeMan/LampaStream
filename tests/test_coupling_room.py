"""Saved LMS room identity is coupling-owned, migrates once and refreshes read-only."""
import asyncio
from unittest.mock import Mock

from lampastream.models import Coupling, VirtualPlayer
from lampastream.player_manager import PlayerManager
from lampastream.storage import Storage


def test_room_roundtrip_activation_rename_and_legacy_migration(tmp_path, monkeypatch):
    import lampastream.player_manager as pm
    storage = Storage(tmp_path/'config.json')
    player = VirtualPlayer(lms_host='127.0.0.1', follow_player_mac='aa:bb:cc:dd:ee:ff')
    storage.save_virtual_player(player)
    coupling = Coupling(player_id=player.id)
    assert coupling.follow_player_mac is None
    manager = PlayerManager(storage)
    rooms = Mock(return_value=[dict(playerid=player.follow_player_mac, name='Living room')])
    monkeypatch.setattr(pm, 'list_lms_players', rooms)
    async def forbidden(*args, **kwargs):
        raise AssertionError('Activation must not discover a room')
    monkeypatch.setattr(pm, 'discover_lms', forbidden)
    selected = asyncio.run(manager._prepare_follow_room(coupling, player))
    assert selected.follow_player_mac == player.follow_player_mac
    assert storage.get_coupling(coupling.id).follow_player_name == 'Living room'
    loaded = Storage(tmp_path/'config.json').get_coupling(coupling.id)
    assert loaded.follow_player_mac == player.follow_player_mac
    # A coupling can choose a different room without changing its shared VirtualPlayer.
    loaded.follow_player_mac = 'aa:bb:cc:dd:ee:01'
    rooms.return_value = [dict(playerid=loaded.follow_player_mac, name='Renamed room')]
    selected = asyncio.run(manager._prepare_follow_room(loaded, player))
    assert selected.follow_player_mac == loaded.follow_player_mac
    assert player.follow_player_mac == 'aa:bb:cc:dd:ee:ff'
    assert storage.get_coupling(loaded.id).follow_player_name == 'Renamed room'
    rooms.side_effect = OSError('offline')
    selected = asyncio.run(manager._prepare_follow_room(loaded, player))
    assert selected.follow_player_mac == loaded.follow_player_mac
    assert loaded.follow_player_name == 'Renamed room'
    legacy = Coupling.from_dict({'id': 'old', 'player_id': player.id})
    assert legacy.follow_player_mac is None
    assert rooms.call_count == 3


def test_saved_room_selects_manual_follow_without_changing_sync_group_default(tmp_path):
    player = VirtualPlayer(follow_mode='sync_group')
    coupling = Coupling(follow_player_mac='aa:bb:cc:dd:ee:ff')
    manager = PlayerManager(Storage(tmp_path/'config.json'))
    selected = asyncio.run(manager._prepare_follow_room(coupling, player))
    assert selected.follow_mode == 'manual'
    assert player.follow_mode == 'sync_group'
    legacy = Coupling()
    selected = asyncio.run(manager._prepare_follow_room(legacy, player))
    assert selected.follow_mode == 'sync_group'


def test_activation_passes_the_saved_room_without_discovery(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from test_player_manager import _make_full_storage

    import lampastream.player_manager as pm
    storage, coupling = _make_full_storage(tmp_path)
    coupling.follow_player_mac = 'aa:bb:cc:dd:ee:01'
    coupling.follow_player_name = 'Cached room'
    storage.save_coupling(coupling)
    manager = PlayerManager(storage)
    monkeypatch.setattr(manager, 'start', lambda: None)
    activate = AsyncMock()
    monkeypatch.setattr(manager, '_activate_lms', activate)
    monkeypatch.setattr(pm, 'list_entertainment_areas', AsyncMock(
        return_value=[SimpleNamespace(id='ae-001', name='Area')]))
    monkeypatch.setattr(pm, 'get_channel_infos', AsyncMock(return_value=[]))
    discovery = AsyncMock(side_effect=AssertionError('No discovery on activation'))
    monkeypatch.setattr(pm, 'discover_lms', discovery)
    monkeypatch.setattr(pm, 'list_lms_players', Mock(return_value=[
        dict(playerid=coupling.follow_player_mac, name='Renamed room')]))
    async def run():
        await manager.activate_coupling(coupling)
        selected = activate.await_args.args[2]
        assert selected.follow_player_mac == coupling.follow_player_mac
        assert selected.follow_mode == 'manual'
        assert storage.get_coupling(coupling.id).follow_player_name == 'Renamed room'
        discovery.assert_not_awaited()
        await manager.close()
    asyncio.run(run())
