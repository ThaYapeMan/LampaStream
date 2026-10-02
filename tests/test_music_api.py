"""Music configuration stays render-only; secrets never enter ordinary responses."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lampastream.api import router
from lampastream.models import Coupling, Effect
from lampastream.storage import Storage


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.storage = Storage(tmp_path / "config.json")
    app.state.player_manager = Mock(active_coupling_id=None)
    client = TestClient(app)
    client.storage = app.state.storage
    client.manager = app.state.player_manager
    return client


def test_palette_crud_preview_duplicate_and_referenced_delete(client):
    assert len(client.get("/api/palettes").json()) == 12
    body = {
        "name": "My colours",
        "stops": [{"colour": "#ff0000", "position": 0}, {"colour": "#0000ff", "position": 100}],
    }
    response = client.post("/api/palettes", json=body)
    assert response.status_code == 201
    identity = response.json()["id"]
    preview = client.post("/api/palettes/preview", json=dict(body, positions=[0, 0.5, 1])).json()
    assert len(preview) == 3 and preview[0] != preview[2]
    body["name"] = "Edited"
    assert client.put(f"/api/palettes/{identity}", json=body).json()["name"] == "Edited"
    duplicate = client.post(f"/api/palettes/{identity}/clone").json()
    assert duplicate["id"] != identity and duplicate["stops"] == body["stops"]
    assert client.delete(f"/api/palettes/{identity}").status_code == 204
    effect = Effect(palette_id=duplicate["id"])
    client.storage.save_effect(effect)
    # The application installs the standard reference-error handler; storage guarantees refusal.
    with pytest.raises(ValueError, match="Reassign"):
        client.storage.delete_palette(duplicate["id"])
    client.manager.activate_coupling.assert_not_called()


def test_music_settings_redacts_key_and_does_not_restart(client):
    response = client.patch(
        "/api/music-settings", json={"lastfm_api_key": "PRIVATE", "lastfm_enabled": True}
    )
    assert response.status_code == 200 and "PRIVATE" not in response.text
    assert client.storage.music_settings().lastfm_api_key == "PRIVATE"
    assert client.get("/api/music-settings").json()["api_key_configured"] is True
    assert "PRIVATE" not in client.get("/api/music-settings").text
    client.patch("/api/music-settings", json={"lastfm_enabled": False})
    assert client.storage.music_settings().lastfm_enabled is False
    client.manager.activate_coupling.assert_not_called()


def test_rules_edit_identity_and_manual_choices_are_persisted(client):
    first = client.post("/api/genre-rules", json={"genre": "house", "palette_id": "neon"}).json()
    updated = client.put(
        f"/api/genre-rules/{first['id']}", json={"genre": "jazz", "palette_id": "ocean"}
    )
    assert updated.status_code == 200
    assert [r.genre for r in client.storage.list_genre_rules()] == ["jazz"]
    coupling = Coupling()
    client.storage.save_coupling(coupling)
    client.manager.active_coupling_id = coupling.id
    assert client.put("/api/music/override", json={"palette_id": "album-art"}).status_code == 200
    assert client.storage.get_coupling(coupling.id).manual_palette_id == "album-art"
    client.put("/api/music/override", json={})
    assert client.storage.get_coupling(coupling.id).manual_palette_id == ""
    client.manager.activate_coupling.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"transition_duration_s": 3},
        {"transition_mode": "push"},
        {"genre_mapping": {"tag": "unknown"}},
    ],
)
def test_music_settings_rejects_invalid_configuration(client, payload):
    assert client.patch("/api/music-settings", json=payload).status_code == 422


def test_effect_palette_reference_and_legacy_response(client):
    effect = client.post("/api/effects", json={"name": "New", "palette_id": "ocean"})
    assert effect.status_code == 201
    assert effect.json()["palette_id"] == "ocean"
    assert "gradient_palette" in effect.json() and len(effect.json()["band_colours"]) == 3
    identity = effect.json()["id"]
    assert (
        client.patch(f"/api/effects/{identity}", json={"palette_id": "missing"}).status_code == 422
    )
