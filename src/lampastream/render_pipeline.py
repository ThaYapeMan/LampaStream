"""The single stateful render path; scenes returned from it have pure samples."""
from __future__ import annotations

from dataclasses import replace

from .output_boundary import BoundaryScene, QuantisationGuard

ENVELOPES = ('onset_envelope', 'onset_envelope_bass', 'onset_envelope_mid',
             'onset_envelope_treble', 'beat_envelope', 'downbeat_envelope', 'texture_envelope')


class RenderPipeline:
    """One session's event view, effect/mixer, accent, preview and output boundary.

    The engine owns the mutable effect/event state for its existing control API;
    this object is the sole caller that advances that state. It knows no player,
    ingress, output brand, latency probe or wall-clock sampling side effects.
    """

    def __init__(self, engine, capabilities, positions):
        self.engine = engine
        self.positions = positions
        self.guard = QuantisationGuard(capabilities)

    def render(self, features, t_audible, preview_audible, unsent=None):
        engine = self.engine
        features = engine._event_view(features, t_audible)
        if unsent is not None:
            features = replace(features, **{key: max(getattr(features, key), getattr(unsent, key))
                                            for key in ENVELOPES})
        engine._preview_shift = max(0., preview_audible-t_audible)
        scene = engine._render_scene(features, t_audible)
        if engine._onset_lift_enabled():
            legacy = engine.profile.diagnostic_onsets
            amplitude = (features.onset_envelope if legacy else
                         max(features.beat_envelope, .1*features.texture_envelope))
            scene = BoundaryScene(scene, self.guard, self.positions, t_audible,
                amplitude > self.guard.lsb,
                minimum_lift=legacy or features.beat_envelope >= .5)
        return scene, features
