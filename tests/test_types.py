"""Tests for the core domain types in lampastream.types."""

from lampastream.types import Colour, Position, UniformScene

# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def test_colour_to_16bit_black():
    assert Colour(0.0, 0.0, 0.0).to_16bit() == (0, 0, 0)


def test_colour_to_16bit_white():
    assert Colour(1.0, 1.0, 1.0).to_16bit() == (65535, 65535, 65535)


def test_colour_to_16bit_midpoint():
    r, g, b = Colour(0.5, 0.5, 0.5).to_16bit()
    # 0.5 × 65535 = 32767 (integer truncation)
    assert r == 32767
    assert g == 32767
    assert b == 32767


def test_colour_to_16bit_clamps_above_one():
    r, g, b = Colour(2.0, 0.5, 0.5).to_16bit()
    assert r == 65535  # clamped


def test_colour_to_16bit_clamps_below_zero():
    r, g, b = Colour(-1.0, 0.5, 0.5).to_16bit()
    assert r == 0  # clamped


def test_colour_lerp_to_self():
    c = Colour(0.2, 0.4, 0.6)
    assert c.lerp(c, 0.5) == c


def test_colour_lerp_boundaries():
    a = Colour(0.0, 0.0, 0.0)
    b = Colour(1.0, 1.0, 1.0)
    assert a.lerp(b, 0.0) == a
    assert a.lerp(b, 1.0) == b


def test_colour_lerp_midpoint():
    a = Colour(0.0, 0.0, 0.0)
    b = Colour(1.0, 1.0, 1.0)
    mid = a.lerp(b, 0.5)
    assert abs(mid.r - 0.5) < 1e-9
    assert abs(mid.g - 0.5) < 1e-9
    assert abs(mid.b - 0.5) < 1e-9


def test_colour_sentinels():
    assert Colour.BLACK == Colour(0.0, 0.0, 0.0)
    assert Colour.WHITE == Colour(1.0, 1.0, 1.0)


def test_colour_frozen():
    """Colour is a frozen dataclass — attribute assignment must raise."""
    import pytest

    c = Colour(0.5, 0.5, 0.5)
    with pytest.raises((AttributeError, TypeError)):
        c.r = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# UniformScene
# ---------------------------------------------------------------------------


def test_uniform_scene_same_colour_everywhere():
    colour = Colour(0.3, 0.5, 0.7)
    scene = UniformScene(colour)
    p1 = Position(0.0, 0.0, 0.0)
    p2 = Position(1.0, -1.0, 0.5)
    assert scene.color_at(p1, 0.0) == colour
    assert scene.color_at(p2, 99.0) == colour


def test_uniform_scene_ignores_time():
    colour = Colour(0.1, 0.2, 0.3)
    scene = UniformScene(colour)
    pos = Position(0.0, 0.0, 0.0)
    assert scene.color_at(pos, 0.0) == scene.color_at(pos, 1000.0)
