"""Regression for the ROUTE-01 AirPlay field failure; no external devices."""
from lampastream.models import Profile
from lampastream.sync_engine import LayerMixer, SmoothLayerMixer
from lampastream.types import AudioFeatures, Position


def test_field_failure_sampling_cannot_rewind_mixer():
    profile = Profile(transition_duration_s=.7)
    features = AudioFeatures([.1]*30, .1, .1, .1, .1)
    previous = LayerMixer(profile, profile)
    mixer = SmoothLayerMixer(profile, profile, previous, lambda: (None, 0.))
    scene = mixer.render(features, 10.)
    point = Position(0, 0, 0)
    initial = scene.color_at(point, 10.)
    scene.color_at(point, 11.)
    scene.color_at(point, 9.)
    assert scene.color_at(point, 10.) == initial
    mixer.render(features, 11.)
    assert mixer.phase.completed and mixer.previous is None
    scene.color_at(point, 9.)
    assert mixer.phase.completed
    mixer.render(features, 11.1)
    print('field failure: render, sample t+1, sample t-1, render; no exception; pure samples')



def test_field_configuration_full_clicks_with_preview_socket(tmp_path, monkeypatch):
    import test_preview_onsets
    from replay_chain import Replay

    class UpdatingReplay(Replay):
        def observe_mixer(self, engine):
            engine.update_render(engine.profile, self.low)
            assert isinstance(engine._effect, SmoothLayerMixer)
            super().observe_mixer(engine)

    monkeypatch.setattr(test_preview_onsets, 'Replay', UpdatingReplay)
    starts = test_preview_onsets.replay_preview(tmp_path, monkeypatch, 'timestamped')
    assert len(starts) == 19
    print('field configuration: SmoothLayerMixer + attached preview socket; '
          'full clicks-120; 19/19 events sent; no exception')
