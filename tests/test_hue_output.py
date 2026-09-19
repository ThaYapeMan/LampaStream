"""Tests for HueDriver (hue_output.py).

HueDriver talks to a real Hue bridge in production.  These tests use a
minimal stub session so no network or DTLS connection is required.
"""

from __future__ import annotations

from lampastream.hue_output import ChannelInfo, HueDriver, HueOutputConfig
from lampastream.models import BridgeConfig
from lampastream.types import Colour, Position, UniformScene

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _config() -> HueOutputConfig:
    bridge = BridgeConfig(name="Test bridge", host="192.168.1.2", app_key="k", client_key="c")
    return HueOutputConfig(bridge=bridge, area_id="area-1", area_name="Living room")


def _channels() -> list[ChannelInfo]:
    return [
        ChannelInfo(channel_id=0, position=Position(-1.0, 0.0, 0.0)),
        ChannelInfo(channel_id=1, position=Position(0.0, 0.0, 0.0)),
        ChannelInfo(channel_id=2, position=Position(1.0, 0.0, 0.0)),
    ]


class _FakeSession:
    """Records what HueDriver.send() passes to the underlying session."""

    def __init__(self) -> None:
        self.calls: list[list] = []

    def send(self, commands: list) -> None:
        self.calls.append(commands)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hue_driver_send_noop_before_start():
    """send() before start() (session=None) must not raise and last_colours stays empty."""
    driver = HueDriver(_config(), _channels())
    scene = UniformScene(Colour(1.0, 0.0, 0.0))
    driver.send(scene, 0.0)  # should be a silent no-op
    assert driver.last_colours == []


def test_hue_driver_send_updates_last_colours():
    """send() must store one Colour per channel in last_colours."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    scene = UniformScene(Colour(0.5, 0.3, 0.1))
    driver.send(scene, 0.0)

    assert len(driver.last_colours) == 3
    for colour in driver.last_colours:
        assert colour == Colour(0.5, 0.3, 0.1)


def test_hue_driver_send_calls_session_with_correct_channel_ids():
    """send() must produce one LightColorCommand per channel with the right channel_id."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    driver.send(UniformScene(Colour(1.0, 1.0, 1.0)), 0.0)

    assert len(fake.calls) == 1
    commands = fake.calls[0]
    assert len(commands) == 3
    ids = {c.channel_id for c in commands}
    assert ids == {0, 1, 2}


def test_hue_driver_send_converts_colour_to_16bit():
    """The LightColorCommands sent to the session must use 16-bit values."""
    driver = HueDriver(_config(), _channels())
    fake = _FakeSession()
    driver._session = fake  # type: ignore[assignment]

    driver.send(UniformScene(Colour(1.0, 0.5, 0.0)), 0.0)

    commands = fake.calls[0]
    for cmd in commands:
        assert cmd.red == 65535
        assert cmd.green == 32767
        assert cmd.blue == 0


def test_hue_driver_last_colours_empty_on_new_instance():
    """A freshly constructed HueDriver must report an empty last_colours list."""
    driver = HueDriver(_config(), _channels())
    assert driver.last_colours == []
