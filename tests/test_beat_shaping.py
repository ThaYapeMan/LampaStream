import colorsys
import math

import pytest

from lampastream.accent import INTENSITIES, AccentLayer, _linear
from lampastream.models import Profile
from lampastream.onset_envelope import TriggerEnvelope
from lampastream.types import AudioFeatures, Colour, Position, UniformScene


@pytest.mark.parametrize('hz', [25, 60])
@pytest.mark.parametrize('intensity', list(INTENSITIES))
def test_flash_falls_between_kicks_in_linear_light(hz, intensity):
    profile = Profile(beat_intensity=intensity)
    envelope = TriggerEnvelope(2/hz, profile.beat_fall_ms/1000/math.log(10))
    envelope.trigger(1., .5)
    scene = UniformScene(Colour(.1, .2, .3))
    layer = AccentLayer()
    values = []
    for t in (.5, .99):
        features = AudioFeatures([], 0, 0, 0, 0, beat_envelope=envelope.value(t))
        colour = layer.render(scene, features, profile).color_at(Position(0, 0, 0), t)
        values.append(_linear(colour.b)/_linear(.3))
        assert colorsys.rgb_to_hsv(colour.r, colour.g, colour.b)[0] == pytest.approx(
            colorsys.rgb_to_hsv(.1, .2, .3)[0])
        assert sum(v >= 1 for v in (colour.r, colour.g, colour.b)) <= 1
    assert values[0] > values[1]
    # Intense strikes to full; its end-of-fall contribution must also disappear.
    assert values[1] <= INTENSITIES[intensity][0]+.1


def test_pad_is_exactly_the_floor_and_texture_is_small():
    scene = UniformScene(Colour(.1, .2, .3))
    profile = Profile()
    layer = AccentLayer()
    point = Position(0, 0, 0)
    floor = layer.render(scene, AudioFeatures([], 0, 0, 0, 0), profile).color_at(point, 0)
    kick = layer.render(scene, AudioFeatures([], 0, 0, 0, 0, beat_envelope=1),
                        profile).color_at(point, 0)
    hat = layer.render(scene, AudioFeatures([], 0, 0, 0, 0, texture_envelope=1),
                       profile).color_at(point, 0)
    assert _linear(floor.b)/_linear(.3) == pytest.approx(.6)
    assert hat.b-floor.b <= .25*(kick.b-floor.b)
