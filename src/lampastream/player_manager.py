"""Process lifecycle: yeney-player, canonical PCM analysis and Hue Entertainment,
all tied to the currently active Profile.

Only one profile can be active at a time (a Hue Bridge only supports a
single Entertainment stream), which this class enforces directly rather
than letting a second `start()` collide with the bridge's own rejection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .airplay_config import (
    disable_early_delivery,
    installed_delivery_margin,
    rename_receiver,
    timing_settings,
)
from .airplay_early import EarlyAirPlaySource
from .airplay_timing import AirPlayAutoLatencyProbe, TimingDiagnostics
from .hue_bridge import list_entertainment_areas
from .hue_output import ChannelInfo, HueDriver, HueOutputConfig, get_channel_infos
from .latency import AutoLatencyProbe, FixedLatencyProbe, NoLatencyProbe, latency_status
from .lms_discovery import discover_lms
from .lms_follower import LmsFollower, LmsSyncGroupObserver, TransportAction
from .lms_status import query_lms_status, query_lms_sync_peers, unsync_player
from .models import BridgeConfig, Controller, Coupling, Profile, VirtualPlayerType
from .pcm_source import (
    AirPlayPipeStereoSource,
    SqueezeliteShmStereoSource,
    TeePcmSource,
)
from .spectrum_engine import make_spectrum_engine as _make_spectrum_engine
from .storage import Storage
from .sync_engine import CanonicalAnalysisPipeline, SyncEngine
from .track_position import (
    AirPlayTrackPositionSource,
    LmsTrackPositionSource,
    TrackPosition,
    TrackPositionSource,
)
from .types import Colour, LatencyProbe
from .util import generate_locally_administered_mac

log = logging.getLogger(__name__)


def _make_canonical_pipeline(
    source: object,
    profile: Profile,
) -> CanonicalAnalysisPipeline:
    """Construct the canonical PCM analysis pipeline selected by profile.spectrum_backend.

    Uses the engine registry so adding a new engine requires no changes here.
    Raises RuntimeError if the selected engine is not available on this system.
    """
    engine = _make_spectrum_engine(
        profile.spectrum_backend,
        n_bars=profile.bars,
        lower_hz=float(profile.lower_cutoff_freq),
        upper_hz=float(profile.higher_cutoff_freq),
    )
    return CanonicalAnalysisPipeline(
        source=source,
        engine=engine,
        onset_method=profile.onset_method,
        onset_delta=profile.onset_delta,
        onset_alpha=profile.onset_alpha,
        superflux_mu=profile.superflux_mu,
        superflux_lag=profile.superflux_lag,
        bass_hz=profile.bass_hz,
        mid_hz=profile.mid_hz,
        band_normalise=profile.band_normalise,
        exertion_clip=profile.exertion_clip,
        use_hpss_separation=profile.use_hpss_separation,
    )


def _controller_to_bridge(controller: Controller) -> BridgeConfig:
    """Convert a Controller entity to the BridgeConfig that Hue functions expect."""
    return BridgeConfig(
        id=controller.id,
        name=controller.name,
        host=controller.host,
        app_key=controller.app_key,
        client_key=controller.client_key,
    )


def _palette_fields(effect, coupling, storage):
    identity = coupling.manual_palette_id or effect.palette_id
    palette = storage.get_palette(identity)
    if palette is None:
        from .palettes import palette_from_colours, starter_palettes
        palette = (next((p for p in starter_palettes() if p.id == effect.gradient_palette), None)
                   if effect.effect_type == "gradient" else None)
        palette = palette or palette_from_colours(effect.name + " colours", effect.band_colours)
    settings = storage.music_settings()
    return dict(palette_id=identity, palette_stops=palette.stops if palette else [],
                palette_rotation_cps=effect.palette_rotation_cps,
                transition_mode=settings.transition_mode,
                transition_duration_s=settings.transition_duration_s)


def _build_engine_profile(coupling: Coupling, storage: Storage) -> Profile | None:
    """Build a Profile from a Coupling's linked entities.

    Returns None if any referenced entity is missing (broken FK).  Used
    internally so that SyncEngine keeps receiving a Profile while the
    rest of the stack works with Coupling + entities.
    """
    player = storage.get_virtual_player(coupling.player_id)
    zone   = storage.get_zone(coupling.zone_id)
    ac     = storage.get_analyser(coupling.analyser_id)
    cf     = storage.get_energy_profile(coupling.energy_profile_id)
    effect = storage.get_effect(cf.high_energy_effect_id) if cf else None
    if not all([player, zone, ac, cf, effect]):
        return None
    return Profile(
        id=coupling.id,
        name=coupling.name,
        lms_host=player.lms_host,
        lms_port=player.lms_port,
        player_name=player.player_name,
        display_name=player.display_name or player.player_name,
        player_mac=player.player_mac,
        alsa_device=player.alsa_device,
        bridge_id=zone.controller_id,
        entertainment_area_id=zone.entertainment_area_id,
        entertainment_area_name=zone.entertainment_area_name,
        light_count=zone.light_count,
        effect_type=effect.effect_type,
        **_palette_fields(effect, coupling, storage),
        gradient_palette=effect.gradient_palette,
        band_colours=effect.band_colours.copy(),
        band_playback=effect.band_playback,
        band_advance=effect.band_advance,
        band_advance_interval_s=effect.band_advance_interval_s,
        effect_speed=effect.effect_speed,
        effect_decay=effect.effect_decay,
        blend_start=cf.blend_start,
        blend_end=cf.blend_end,
        blend_response=cf.blend_response,
        energy_source=cf.energy_source,
        lufs_floor=cf.lufs_floor,
        lufs_ceiling=cf.lufs_ceiling,
        adaptation_tau_s=cf.adaptation_tau_s,
        peak_envelope_auto=cf.peak_envelope_auto,
        peak_attack_s=cf.peak_attack_s,
        peak_release_s=cf.peak_release_s,
        peak_reshape_enabled=cf.peak_reshape_enabled,
        peak_reshape_power=cf.peak_reshape_power,
        sensitivity=effect.sensitivity,
        brightness_floor=effect.brightness_floor,
        bass_hz=effect.bass_hz,
        mid_hz=effect.mid_hz,
        exertion_clip=effect.exertion_clip,
        onset_flash_intensity=effect.onset_flash_intensity,
        onset_method=ac.onset_method,
        onset_delta=ac.onset_delta,
        onset_alpha=ac.onset_alpha,
        superflux_mu=ac.superflux_mu,
        superflux_lag=ac.superflux_lag,
        use_hpss_separation=ac.use_hpss_separation,
        band_normalise=ac.band_normalise,
        bars_source=ac.bars_source,
        spectrum_backend=ac.spectrum_backend,
        bars=ac.bars,
        lower_cutoff_freq=ac.lower_cutoff_freq,
        higher_cutoff_freq=ac.higher_cutoff_freq,
        enabled=coupling.enabled,
    )


def _build_mellow_profile(coupling: Coupling, storage: Storage) -> Profile | None:
    """Build a Profile for the low-energy (quiet-passage) layer from the EnergyProfile's low Effect.

    Returns None if the energy profile has no low_energy_effect_id or the entity is
    missing — the caller (SyncEngine) then falls back to the active profile for
    both layers, which is a valid no-op state.
    """
    cf = storage.get_energy_profile(coupling.energy_profile_id)
    if not cf or not cf.low_energy_effect_id:
        return None
    mellow_effect = storage.get_effect(cf.low_energy_effect_id)
    if mellow_effect is None:
        return None

    # All non-Effect fields (player, LMS, analysis, zone) are the same as the
    # active profile; only the Effect-derived fields differ.
    player = storage.get_virtual_player(coupling.player_id)
    zone   = storage.get_zone(coupling.zone_id)
    ac     = storage.get_analyser(coupling.analyser_id)
    if not all([player, zone, ac]):
        return None
    return Profile(
        id=coupling.id,
        name=coupling.name,
        lms_host=player.lms_host,
        lms_port=player.lms_port,
        player_name=player.player_name,
        display_name=player.display_name or player.player_name,
        player_mac=player.player_mac,
        alsa_device=player.alsa_device,
        bridge_id=zone.controller_id,
        entertainment_area_id=zone.entertainment_area_id,
        entertainment_area_name=zone.entertainment_area_name,
        light_count=zone.light_count,
        effect_type=mellow_effect.effect_type,
        **_palette_fields(mellow_effect, coupling, storage),
        gradient_palette=mellow_effect.gradient_palette,
        band_colours=mellow_effect.band_colours.copy(),
        band_playback=mellow_effect.band_playback,
        band_advance=mellow_effect.band_advance,
        band_advance_interval_s=mellow_effect.band_advance_interval_s,
        effect_speed=mellow_effect.effect_speed,
        effect_decay=mellow_effect.effect_decay,
        blend_start=cf.blend_start,
        blend_end=cf.blend_end,
        blend_response=cf.blend_response,
        energy_source=cf.energy_source,
        lufs_floor=cf.lufs_floor,
        lufs_ceiling=cf.lufs_ceiling,
        adaptation_tau_s=cf.adaptation_tau_s,
        peak_envelope_auto=cf.peak_envelope_auto,
        peak_attack_s=cf.peak_attack_s,
        peak_release_s=cf.peak_release_s,
        peak_reshape_enabled=cf.peak_reshape_enabled,
        peak_reshape_power=cf.peak_reshape_power,
        sensitivity=mellow_effect.sensitivity,
        brightness_floor=mellow_effect.brightness_floor,
        bass_hz=mellow_effect.bass_hz,
        mid_hz=mellow_effect.mid_hz,
        exertion_clip=mellow_effect.exertion_clip,
        onset_flash_intensity=mellow_effect.onset_flash_intensity,
        onset_method=ac.onset_method,
        onset_delta=ac.onset_delta,
        onset_alpha=ac.onset_alpha,
        superflux_mu=ac.superflux_mu,
        superflux_lag=ac.superflux_lag,
        use_hpss_separation=ac.use_hpss_separation,
        band_normalise=ac.band_normalise,
        bars_source=ac.bars_source,
        spectrum_backend=ac.spectrum_backend,
        bars=ac.bars,
        lower_cutoff_freq=ac.lower_cutoff_freq,
        higher_cutoff_freq=ac.higher_cutoff_freq,
        enabled=coupling.enabled,
    )


def _log_task_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("Background task %r raised an exception", task.get_name(), exc_info=exc)

_RUN_DIR = Path(tempfile.gettempdir()) / "lampastream"


class ActiveSession:
    def __init__(
        self,
        profile: Profile,
        coupling: Coupling | None = None,
        player_type: VirtualPlayerType = VirtualPlayerType.LMS,
    ):
        self.profile = profile
        self.stopping = False  # source still owned until teardown completes
        self.coupling = coupling
        self.player_type = player_type
        self.lms_player: subprocess.Popen | None = None
        self.sync_engine: SyncEngine | None = None
        self.hue_driver: HueDriver | None = None
        self.task: asyncio.Task | None = None
        self.probe: LatencyProbe = NoLatencyProbe()
        self.latency_preferences: dict[str, int] = {}
        self.latency_mac: str | None = None
        self.poller_task: asyncio.Task | None = None
        self.music_task: asyncio.Task | None = None
        self.music = None
        self.shm_source: TeePcmSource | None = None
        self.follower: LmsFollower | None = None
        self.follower_task: asyncio.Task | None = None
        self.head_start_task: asyncio.Task | None = None
        self.unsync_task: asyncio.Task | None = None
        self.track_source: TrackPositionSource | None = None
        self.safety_task: asyncio.Task | None = None


class PlayerManager:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.airplay_timing = TimingDiagnostics()
        self._active: ActiveSession | None = None
        self._session_lock = asyncio.Lock()
        # Metadata belongs to the active receiver session; restart supplies fresh events.
        self._airplay_tracks: AirPlayTrackPositionSource | None = None
        self._airplay_rollback_attempted = False
        self._airplay_safety_message: str | None = None
        self.latency_warning: str | None = None
        self._detected_sync_master: str | None = None
        self._detected_sync_master_name: str | None = None
        _RUN_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def music_status(self):
        if self._active and self._active.music:
            return self._active.music.status.copy()
        return None

    def _start_music(self, session):
        from .music import MusicDirector
        if session.coupling is None:
            return
        def apply(coupling, palette, album):
            if self._active is not session or session.stopping:
                return
            profile = _build_engine_profile(coupling, self.storage)
            mellow = _build_mellow_profile(coupling, self.storage)
            if profile is None:
                return
            for candidate in (profile, mellow):
                if candidate is None:
                    continue
                selected = palette or (album if candidate.palette_id == "album-art" else None)
                if selected:
                    candidate.palette_stops = selected.stops
                elif candidate.palette_id == "album-art":
                    candidate.palette_stops = session.sync_engine.profile.palette_stops
            session.profile = profile
            session.sync_engine.update_render(profile, mellow)
        def current_palette():
            from .palettes import Palette
            stops = session.sync_engine.profile.palette_stops
            return Palette(name="Current colours", stops=stops) if stops else None
        session.music = MusicDirector(self.storage, apply, lambda: self.track_position,
                                      current_palette=current_palette)
        session.music_task = asyncio.create_task(session.music.run(session.coupling),
                                                name="music-colours")
        session.music_task.add_done_callback(_log_task_failure)

    def refresh_music(self):
        if self._active and self._active.music:
            self._active.music.last_key = None
            self._active.music.applied = None

    @property
    def track_position(self) -> TrackPosition | None:
        session = self._active
        if session and not session.stopping and session.track_source:
            return session.track_source.read()
        return None

    @property
    def configuration_restore_ready(self) -> bool:
        """Only a fully released session permits configuration replacement."""
        return self._active is None

    @property
    def detected_sync_master(self) -> str | None:
        return self._detected_sync_master

    @property
    def detected_sync_master_name(self) -> str | None:
        return self._detected_sync_master_name

    @property
    def follow_target_mac(self) -> str | None:
        session = self._active
        if (not session or session.stopping or session.player_type != VirtualPlayerType.LMS
                or not session.follower):
            return None
        target = session.follower.target_mac
        managed = {p.player_mac.lower() for p in self.storage.list_virtual_players()}
        managed.add(session.profile.player_mac.lower())
        if (not target or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", target)
                or target.lower() in managed):
            return None
        return target

    @property
    def follow_target_name(self) -> str | None:
        target = self.follow_target_mac
        if target and target == self._detected_sync_master:
            return self._detected_sync_master_name or target
        return target

    async def control_followed_player(self, coupling_id: str, action: TransportAction) -> str:
        session = self._active
        if not session or session.stopping or self.active_coupling_id != coupling_id:
            raise RuntimeError("Coupling is not active")
        # AirPlay transport needs Shairport's DACP/MPRIS remote-control path;
        # it is deliberately outside this LMS-only endpoint.
        target = self.follow_target_mac
        if target is None or session.follower is None:
            raise RuntimeError("No controllable followed LMS player")
        task = asyncio.create_task(
            asyncio.to_thread(session.follower.control_target, action, target)
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Keep the API mutation guard until the bounded CLI write finishes,
            # so teardown/replacement cannot overtake an abandoned command.
            await task
            raise
        return target

    @property
    def follower_warning(self) -> str | None:
        """Human-readable warning when the LMS follower is disconnected, else None."""
        if self._active and self._active.follower:
            return self._active.follower.warning
        return None

    @property
    def analysis_stopping(self) -> bool:
        """An owned session is stopping; activation must complete its teardown."""
        return bool(self._active and self._active.stopping)

    @property
    def active_coupling_id(self) -> str | None:
        if self._active and self._active.coupling:
            return self._active.coupling.id
        return None

    @property
    def active_zone_id(self) -> str | None:
        if self._active and self._active.coupling:
            return self._active.coupling.zone_id
        return None

    @property
    def last_channel_infos(self) -> list[ChannelInfo]:
        if self._active and self._active.hue_driver:
            return self._active.hue_driver.channels
        return []

    @property
    def last_colours(self) -> list[Colour]:
        if self._active and self._active.hue_driver:
            return self._active.hue_driver.last_colours
        return []

    @property
    def last_onset(self) -> bool:
        """True if the most recently analysed frame contained a detected onset.

        Reflects the raw detection result without any output delay applied,
        so the GUI can show onset flashes in sync with the audio rather than
        with the delayed light output.
        """
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_onset
        return False

    @property
    def last_pcm_onset(self) -> bool:
        """True if the PCM-tap onset pipeline detected an onset this tick."""
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_pcm_onset
        return False

    @property
    def last_onset_bass(self) -> bool:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_onset_bass
        return False

    @property
    def last_onset_mid(self) -> bool:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_onset_mid
        return False

    @property
    def last_onset_treble(self) -> bool:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_onset_treble
        return False

    @property
    def process_status(self) -> dict[str, bool]:
        if not self._active:
            return {"lms_player": False}
        if self._active.player_type == VirtualPlayerType.AIRPLAY:
            return {"lms_player": False}
        player_process = self._active.lms_player
        return {
            "lms_player": bool(player_process and player_process.poll() is None),
        }

    @property
    def active_player_type(self) -> str | None:
        """The type string of the active player, or None if no session is active."""
        if self._active:
            return self._active.player_type.value
        return None

    @property
    def airplay_receiving(self) -> bool | None:
        """True/False when an AirPlay player is active; None otherwise."""
        if not self._active or self._active.player_type != VirtualPlayerType.AIRPLAY:
            return None
        src = self._active.shm_source
        return src.running if src is not None else False

    @property
    def applied_delay_ms(self) -> int:
        if not self._active:
            return 0
        lms = self.lms_timing
        if lms and lms["state"] == "scheduled" and lms.get("lead_p5_ms") is not None:
            return max(0, round(lms["available_ms"] + lms["trim_ms"]))
        return self._active.probe.current_delay_ms()

    @property
    def output_status(self) -> dict | None:
        if self._active and self._active.hue_driver:
            result = self._active.hue_driver.output_status
            return result if isinstance(result, dict) else None
        return None

    @property
    def bridge_connected(self) -> bool:
        return bool(self.output_status and self.output_status["state"] == "streaming")

    @property
    def preview_spectrum(self) -> tuple[list[float], list[float] | None]:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.preview_spectrum
        return [], None

    @property
    def last_bars(self) -> list[float]:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_bars
        return []

    @property
    def last_mix(self) -> float:
        """Current LayerMixer crossfade value (0.0 = mellow, 1.0 = active)."""
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_mix
        return 0.0

    @property
    def last_energy(self) -> float:
        """Raw full-band energy of the last frame (0.0–1.0)."""
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_energy
        return 0.0

    @property
    def last_energy_input(self) -> float:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_energy_input
        return 0.0

    @property
    def last_loudness(self) -> tuple[float | None, float | None]:
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_loudness
        return None, None

    @property
    def last_sustained_energy(self) -> float | None:
        """Section-level sustained energy from SustainedEnergyTracker (None if unavailable)."""
        if self._active and self._active.sync_engine:
            return self._active.sync_engine.last_sustained_energy
        return None

    @property
    def active_energy_profile_id(self) -> str | None:
        if self._active and self._active.coupling:
            if self._active.music and self._active.music.status.get("energy_profile_id"):
                return self._active.music.status["energy_profile_id"]
            return self._active.coupling.energy_profile_id
        return None

    @property
    def active_coupling_name(self) -> str | None:
        if self._active and self._active.coupling:
            return self._active.coupling.name
        return None

    @property
    def active_lower_cutoff_freq(self) -> int | None:
        return self._active.profile.lower_cutoff_freq if self._active else None

    @property
    def active_higher_cutoff_freq(self) -> int | None:
        return self._active.profile.higher_cutoff_freq if self._active else None

    @property
    def active_bass_hz(self) -> int | None:
        return self._active.profile.bass_hz if self._active is not None else None

    @property
    def active_mid_hz(self) -> int | None:
        return self._active.profile.mid_hz if self._active is not None else None

    @property
    def active_effect(self) -> str | None:
        """Return the currently active effect ID, or None if no session is active."""
        if self._active:
            return self._active.profile.effect_type
        return None

    @property
    def active_onset_method(self) -> str | None:
        return self._active.profile.onset_method if self._active else None

    @property
    def active_sensitivity(self) -> float | None:
        return self._active.profile.sensitivity if self._active else None

    async def activate_coupling(self, coupling: Coupling) -> None:
        async with self._session_lock:
            await self._activate_coupling(coupling)

    async def _activate_coupling(self, coupling: Coupling) -> None:
        """Activate a Coupling, resolving all linked entities natively.

        Controller is used directly for Hue calls instead of the old BridgeConfig
        lookup.  A Profile is built internally so that SyncEngine keeps
        receiving a Profile while the rest of the stack works with entities.
        """
        previous = (self._active.coupling.name
                    if self._active and self._active.coupling else "stopped")
        await self._deactivate_unlocked()

        player = self.storage.get_virtual_player(coupling.player_id)
        zone = self.storage.get_zone(coupling.zone_id)
        ac = self.storage.get_analyser(coupling.analyser_id)
        cf = self.storage.get_energy_profile(coupling.energy_profile_id)
        effect = self.storage.get_effect(cf.high_energy_effect_id) if cf else None

        if not player:
            raise ValueError(f"Coupling references missing VirtualPlayer {coupling.player_id!r}")
        if not zone:
            raise ValueError(
                f"Coupling references missing Zone {coupling.zone_id!r}"
            )
        if not ac:
            raise ValueError(
                f"Coupling references missing Analyser {coupling.analyser_id!r}"
            )
        if not cf:
            raise ValueError(
                f"Coupling references missing EnergyProfile {coupling.energy_profile_id!r}"
            )
        if not effect:
            raise ValueError(
                f"EnergyProfile references missing Effect {cf.high_energy_effect_id!r}"
            )

        controller = self.storage.get_controller(zone.controller_id)
        if not controller:
            raise ValueError(
                f"Zone references missing Controller {zone.controller_id!r}"
            )

        bridge = _controller_to_bridge(controller)
        areas = await list_entertainment_areas(bridge)
        area = next((a for a in areas if a.id == zone.entertainment_area_id), None)
        if area is None:
            raise ValueError("Configured Entertainment Area no longer exists on the controller")

        channels = await get_channel_infos(bridge, zone.entertainment_area_id)

        output_config = HueOutputConfig(
            bridge=bridge,
            area_id=zone.entertainment_area_id,
            area_name=area.name,
        )

        profile = Profile(
            id=coupling.id,
            name=coupling.name,
            lms_host=player.lms_host,
            lms_port=player.lms_port,
            player_name=player.player_name,
            display_name=player.display_name or player.player_name,
            player_mac=player.player_mac,
            alsa_device=player.alsa_device,
            bridge_id=zone.controller_id,
            entertainment_area_id=zone.entertainment_area_id,
            entertainment_area_name=zone.entertainment_area_name,
            light_count=zone.light_count,
            effect_type=effect.effect_type,
            **_palette_fields(effect, coupling, self.storage),
        gradient_palette=effect.gradient_palette,
            band_colours=effect.band_colours.copy(),
            band_playback=effect.band_playback,
            band_advance=effect.band_advance,
            band_advance_interval_s=effect.band_advance_interval_s,
            effect_speed=effect.effect_speed,
            effect_decay=effect.effect_decay,
            blend_start=cf.blend_start,
            blend_end=cf.blend_end,
            blend_response=cf.blend_response,
            energy_source=cf.energy_source,
            lufs_floor=cf.lufs_floor,
            lufs_ceiling=cf.lufs_ceiling,
            adaptation_tau_s=cf.adaptation_tau_s,
            peak_envelope_auto=cf.peak_envelope_auto,
            peak_attack_s=cf.peak_attack_s,
            peak_release_s=cf.peak_release_s,
            peak_reshape_enabled=cf.peak_reshape_enabled,
            peak_reshape_power=cf.peak_reshape_power,
            sensitivity=effect.sensitivity,
            brightness_floor=effect.brightness_floor,
            bass_hz=effect.bass_hz,
            mid_hz=effect.mid_hz,
            exertion_clip=effect.exertion_clip,
            onset_flash_intensity=effect.onset_flash_intensity,
            onset_method=ac.onset_method,
            onset_delta=ac.onset_delta,
            onset_alpha=ac.onset_alpha,
            superflux_mu=ac.superflux_mu,
            superflux_lag=ac.superflux_lag,
            use_hpss_separation=ac.use_hpss_separation,
            band_normalise=ac.band_normalise,
            bars_source=ac.bars_source,
            spectrum_backend=ac.spectrum_backend,
            bars=ac.bars,
            lower_cutoff_freq=ac.lower_cutoff_freq,
            higher_cutoff_freq=ac.higher_cutoff_freq,
            enabled=coupling.enabled,
        )
        mellow_profile = _build_mellow_profile(coupling, self.storage)

        self.latency_warning = None
        self._detected_sync_master = None

        session = ActiveSession(profile, coupling=coupling, player_type=player.type)
        try:
            if player.type == VirtualPlayerType.AIRPLAY:
                await self._activate_airplay(
                    session, profile, mellow_profile, output_config, channels
                )
            elif player.type == VirtualPlayerType.LMS:
                await self._activate_lms(
                    session, profile, player, mellow_profile, output_config, channels
                )
            else:
                raise ValueError(f"Unsupported virtual player type: {player.type!r}")
        except BaseException:
            # Keep ownership even if cleanup itself times out. A subsequent
            # deactivate/activate retries teardown before opening a new source.
            self._active = session
            await self._teardown_session(session)
            self._active = None
            raise

        self._active = session
        self.storage.set_active_coupling_id(coupling.id)
        log.info("coupling switch: %s → %s: source opened / receiver ready / DTLS connected",
                 previous, coupling.name)
        log.info("Activated coupling %s (%s)", coupling.name, coupling.id)

    async def _activate_lms(
        self,
        session: ActiveSession,
        profile: Profile,
        player,
        mellow_profile: Profile | None,
        output_config: HueOutputConfig,
        channels: list[ChannelInfo],
    ) -> None:
        """LMS path: yeney-player + canonical PCM analysis + Hue."""
        self._start_lms_player(session, profile)

        await self._activate_lms_pcm(session, profile, mellow_profile, output_config, channels)

        # Adapter selection is ingress/session responsibility. Downstream sees only
        # TrackPositionSource. Resolve the follower's actual selected MAC dynamically.
        session.track_source = LmsTrackPositionSource(
            player.lms_host,
            lambda: (session.follower.target_mac if session.follower else
                     (None if player.follow_mode == "sync_group" else profile.player_mac)),
        )
        session.track_source.open()

        if player.follow_mode == "sync_group":
            async def target_changed(mac: str | None) -> None:
                if session.stopping:
                    return
                await self._apply_probe_for_master(session, mac)
                self._detected_sync_master = mac
                self._detected_sync_master_name = None
                if mac:
                    try:
                        observed_at = time.monotonic()
                        status = await asyncio.to_thread(query_lms_status, player.lms_host, mac)
                        self._detected_sync_master_name = status.player_name
                        if isinstance(session.track_source, LmsTrackPositionSource):
                            session.track_source.seed(mac, status, observed_at)
                    except OSError:
                        pass  # MAC remains a usable display identity.

            session.follower = LmsSyncGroupObserver(
                player.lms_host, profile.player_mac,
                managed_macs=lambda: [
                    vp.player_mac for vp in self.storage.list_virtual_players()
                ],
                on_target_changed=target_changed,
                on_group_refresh=(session.head_start.group_refresh
                                  if getattr(session, "head_start", None) else None),
            )
            session.follower_task = session.follower.start()
            session.follower_task.add_done_callback(_log_task_failure)
            return  # Auto mode must never schedule the manual unsync path.

        follow_mac = player.follow_player_mac
        if follow_mac:
            session.follower = LmsFollower(
                lms_host=player.lms_host,
                follow_mac=follow_mac,
                lampastream_mac=profile.player_mac,
            )
        else:
            log.warning(
                "Coupling %r: follow_player_mac not configured — "
                "track mirroring disabled. Set it in the Virtual Player editor.",
                session.coupling and session.coupling.name,
            )
        session.unsync_task = asyncio.create_task(
            self._delayed_unsync_and_follow(session, player.lms_host, profile.player_mac),
            name="lms-unsync",
        )
        session.unsync_task.add_done_callback(_log_task_failure)

    async def _activate_lms_pcm(
        self,
        session: ActiveSession,
        profile: Profile,
        mellow_profile: Profile | None,
        output_config: HueOutputConfig,
        channels: list[ChannelInfo],
    ) -> None:
        """LMS pcm_pipeline sub-path: yeney-player + canonical PCM pipeline, no cava/FIFO.

        Uses SqueezeliteShmStereoSource (stereo, SourceReadResult protocol) so the
        shared _make_canonical_pipeline() factory can select v2 or cavacore, identical
        to the AirPlay path.  Both ingresses feed into the same factory.
        """
        await asyncio.to_thread(self._wait_for_shm, profile.player_mac)

        from .lms_timing import LmsHeadStart, LmsTimedSource
        player = (self.storage.get_virtual_player(session.coupling.player_id)
                  if session.coupling else None)
        source = SqueezeliteShmStereoSource()
        session.lms_timed_source = None
        session.head_start = None
        if player and player.follow_mode == "sync_group":
            if player.head_start_ms:
                source = LmsTimedSource(source, player,
                                        lambda: session.track_source.read()
                                        if session.track_source else None, ready=False)
                session.lms_timed_source = source
            session.head_start = LmsHeadStart(player, session.lms_timed_source)
            session.head_start_task = asyncio.create_task(session.head_start.run(),
                                                         name="lms-head-start")
            session.head_start_task.add_done_callback(_log_task_failure)
        shm_source = TeePcmSource(source)
        shm_source.open(profile.player_mac)
        session.shm_source = shm_source

        pcm_analyser = _make_canonical_pipeline(shm_source, profile)

        engine = SyncEngine(
            None, profile, probe=session.probe,
            mellow_profile=mellow_profile, analyser=pcm_analyser,
            timing=(session.lms_timed_source.timing if session.lms_timed_source else None),
        )
        session.sync_engine = engine
        engine.start()

        if session.coupling:
            output_config.release_after_idle_s = session.coupling.release_after_idle_s
            output_config.on_release = session.coupling.on_release
        hue_driver = HueDriver(output_config, channels)
        hue_driver.transport = lambda: session.track_source.read() if session.track_source else None
        await hue_driver.start()
        session.hue_driver = hue_driver

        session.task = asyncio.create_task(engine.run(hue_driver))
        session.task.add_done_callback(_log_task_failure)
        self._start_music(session)
        session.poller_task = asyncio.create_task(self._poll_sync_master(session))
        session.poller_task.add_done_callback(_log_task_failure)
        log.info(
            "LMS pcm_pipeline coupling %s active — backend=%r SHM: /dev/shm/squeezelite-%s",
            session.coupling and session.coupling.name,
            profile.spectrum_backend,
            profile.player_mac,
        )

    async def _activate_airplay(
        self,
        session: ActiveSession,
        profile: Profile,
        mellow_profile: Profile | None,
        output_config: HueOutputConfig,
        channels: list[ChannelInfo],
    ) -> None:
        """One owner per AirPlay FIFO; one canonical stereo analysis path.

        EarlyAirPlaySource chooses timestamped decoded PCM or the regular pipe
        fallback. It drains the unused pipe and never restarts the receiver.
        """
        self.latency_warning = self._airplay_safety_message
        if self._airplay_tracks is None:
            self._airplay_tracks = AirPlayTrackPositionSource(timing=self.airplay_timing)
        session.track_source = self._airplay_tracks
        session.track_source.open()
        ingress = EarlyAirPlaySource(timing=self.airplay_timing,
                                     pipe=AirPlayPipeStereoSource(timing=self.airplay_timing))
        pipe_source = TeePcmSource(ingress)
        pipe_source.open()
        session.shm_source = pipe_source
        await self._receiver_operation(
            self._configure_shairport_name, profile.display_name or profile.player_name)
        self._airplay_tracks.invalidate()
        self.airplay_timing.reset()
        ingress.discard_pending()
        await self._apply_airplay_probe(session)
        session.safety_task = asyncio.create_task(self._watch_airplay_delivery(session))

        pcm_analyser = _make_canonical_pipeline(pipe_source, profile)

        engine = SyncEngine(
            None, profile, probe=session.probe, timing=self.airplay_timing,
            mellow_profile=mellow_profile, analyser=pcm_analyser,
        )
        session.sync_engine = engine
        engine.start()

        if session.coupling:
            output_config.release_after_idle_s = session.coupling.release_after_idle_s
            output_config.on_release = session.coupling.on_release
        hue_driver = HueDriver(output_config, channels)
        hue_driver.transport = lambda: session.track_source.read() if session.track_source else None
        await hue_driver.start()
        session.hue_driver = hue_driver

        session.task = asyncio.create_task(engine.run(hue_driver))
        session.task.add_done_callback(_log_task_failure)
        self._start_music(session)
        log.info(
            "AirPlay coupling %s active — backend=%r pipe: /run/lampastream/airplay.pcm",
            session.coupling and session.coupling.name,
            profile.spectrum_backend,
        )

    async def close(self) -> None:
        """Application shutdown, including the persistent receiver metadata reader."""
        try:
            await self.deactivate()
        finally:
            if self._airplay_tracks is not None:
                await self._airplay_tracks.close()
                self._airplay_tracks = None

    async def deactivate(self) -> None:
        async with self._session_lock:
            await self._deactivate_unlocked()

    async def _deactivate_unlocked(self) -> None:
        if not self._active:
            return
        session = self._active
        self.latency_warning = None
        self._detected_sync_master = None
        self._detected_sync_master_name = None
        await self._teardown_session(session)
        self._active = None
        self.storage.set_active_coupling_id(None)
        if session.coupling:
            log.info("Deactivated coupling %s", session.coupling.name)
        else:
            log.info("Deactivated profile %s", session.profile.name)

    async def _teardown_session(self, session: ActiveSession) -> None:
        session.stopping = True
        if session.track_source is not None:
            await session.track_source.close()
            if session.track_source is self._airplay_tracks:
                self._airplay_tracks = None
            session.track_source = None
        for attribute in ("head_start_task", "unsync_task", "safety_task", "music_task",
                          "poller_task", "task"):
            task = getattr(session, attribute)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                except Exception:
                    log.exception("Session task failed during teardown: %s", attribute)
                setattr(session, attribute, None)
        if session.follower:
            session.follower.stop()
            session.follower = None
        if session.follower_task:
            task = session.follower_task
            task.cancel()
            try:
                # Own completion of the follower's connection cleanup before
                # a retry can cancel it again or start a replacement follower.
                await task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise  # do not swallow cancellation of teardown itself
            session.follower_task = None
        if session.sync_engine:
            stopped = session.sync_engine.stop()
            if stopped is False or session.sync_engine.retirement_pending is True:
                raise RuntimeError(
                    "Analysis worker still retiring; source retained. Retry deactivation "
                    "after the worker exits. No replacement session has been started."
                )
        if session.shm_source is not None:
            session.shm_source.close()
            session.shm_source = None
        await session.probe.stop()
        if session.hue_driver:
            try:
                await session.hue_driver.stop()
            finally:
                # Even a failed HTTP stop must release DTLS. Failure is propagated
                # so activation cannot overlap an unreleased Entertainment session.
                await session.hue_driver.aclose()
            session.hue_driver = None

        for proc in (session.lms_player,):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)

        # yeney-player creates /dev/shm/squeezelite-<mac> and never removes it.
        # Without this, every activate/deactivate cycle leaves an orphaned
        # segment behind — confirmed: 9 segments after a handful of test runs.
        if session.profile.player_mac:
            Path(f"/dev/shm/squeezelite-{session.profile.player_mac}").unlink(
                missing_ok=True
            )

    def cleanup_orphaned_shm(self) -> None:
        """Remove all yeney-player shm segments left by a previous crashed run.

        Safe to call at startup: yeney-player is only ever started by LampaStream,
        and only after the service itself is running.  Any segment present
        when the service starts is therefore stale — including segments from
        pre-fix runs whose random MAC was never persisted to a profile.
        """
        shm_dir = Path("/dev/shm")
        if not shm_dir.is_dir():
            return
        for seg in shm_dir.glob("squeezelite-*"):
            try:
                seg.unlink()
                log.info("Removed orphaned yeney-player shm segment %s", seg.name)
            except OSError as exc:
                log.warning("Could not remove %s: %s", seg.name, exc)

    def update_onset_pipeline(self, profile: Profile) -> None:
        """Switch PCM onset method live on the active session."""
        if self._active and self._active.sync_engine:
            self._active.profile = profile
            self._active.sync_engine.update_onset_pipeline(profile)

    def update_render(self, profile: Profile, mellow_profile: Profile | None = None) -> None:
        """Apply render-only changes live on the active session."""
        if self._active and self._active.sync_engine:
            self._active.profile = profile
            self._active.sync_engine.update_render(profile, mellow_profile)
            self.refresh_music()

    def replace_pcm_analyser(self, profile: Profile) -> None:
        """Transactionally swap the active spectrum engine.

        Semantics:
        1. Snapshot the current profile so we can roll back on failure.
        2. Build a candidate CanonicalAnalysisPipeline WITHOUT touching
           ``self._active``.  If construction itself raises (invalid config,
           unavailable engine) neither the old pipeline nor the session
           profile are touched.
        3. Delegate the atomic stop-old / start-new dance to
           ``SyncEngine.replace_analyser``, supplying a rebuild callable so a
           failed candidate does not leave the runtime without an analyser.
        4. On success: commit ``self._active.profile = profile``.
        5. On failure: restore the previous profile on the session so
           storage, session profile, and runtime stay in sync.  The caller
           (api.py) is responsible for rolling back persisted Analyser
           configuration on the returned exception.
        """
        if self._active is None or self._active.sync_engine is None:
            return
        if self._active.stopping:
            raise RuntimeError(
                "Session is stopping; complete deactivation before replacing analysis"
            )
        source = self._active.shm_source
        if source is None:
            raise RuntimeError("Active session has no canonical PCM source")

        old_profile = self._active.profile

        # Step 1: build candidate first.  If this raises we have not yet
        # stopped the old pipeline, so no rollback is required.
        candidate = _make_canonical_pipeline(source, profile)

        # Rebuild closure — used by SyncEngine.replace_analyser if the
        # candidate fails to start.  It re-uses the exact same source and
        # the pre-swap profile so the analyser matches what storage still
        # (or will) contain after the caller rolls back.
        def _rebuild_old() -> CanonicalAnalysisPipeline:
            return _make_canonical_pipeline(source, old_profile)

        try:
            self._active.sync_engine.replace_analyser(
                candidate, rebuild_old=_rebuild_old
            )
        except Exception:
            # Restore session profile so the runtime matches what the caller
            # will roll storage back to.  The exception propagates so api.py
            # can restore persisted Analyser configuration.
            self._active.profile = old_profile
            if self._active.sync_engine.retirement_pending:
                self._active.stopping = True
            raise

        # SUCCESS: commit new profile only after start succeeded.
        self._active.profile = profile
        self._active.stopping = False
        log.info(
            "replace_pcm_analyser: new spectrum_backend=%r active",
            profile.spectrum_backend,
        )

    async def refresh_probe(self) -> None:
        """Re-evaluate the latency probe for the current sync master.

        Call this after saving or deleting a PlayerLatency entry so that a
        running session picks up the change immediately, without requiring a
        deactivate/reactivate cycle.  Does nothing when no session is active.
        """
        if self._active is None:
            return
        if self._active.player_type == VirtualPlayerType.AIRPLAY:
            await self._apply_airplay_probe(self._active)
        else:
            await self._apply_probe_for_master(self._active, self._detected_sync_master)

    @property
    def follow_mode(self) -> str | None:
        if self._active and self._active.coupling:
            player = self.storage.get_virtual_player(self._active.coupling.player_id)
            return player.follow_mode if player else None
        return None

    @property
    def lms_timing(self):
        session = self._active
        if (not session or getattr(session, "player_type", None) != VirtualPlayerType.LMS
                or not getattr(session, "coupling", None)):
            return None
        player = self.storage.get_virtual_player(session.coupling.player_id)
        if player is None or player.follow_mode != "sync_group":
            return None
        source = getattr(session, "lms_timed_source", None)
        if source:
            data = source.timing.snapshot()
            return dict(source="lms", audio_source=data["tap_source"],
                        provenance=getattr(source, "provenance", "write-clock estimate"),
                        state=(source.readiness_state if not source.ready else
                               ("scheduled" if data["tap_source"] == "LMS head start"
                                else "fallback")),
                        reason=source.reason, head_start_ms=player.head_start_ms,
                        synced_player_name=self._detected_sync_master_name,
                        speaker_output_delay_ms=player.speaker_output_delay_ms,
                        lead_p5_ms=data["lead_p5_ms"], lead_p50_ms=data["lead_p50_ms"],
                        median_processing_ms=data["median_processing_ms"], tap_drop_count=0,
                        timing_generation=data["tap_generation"],
                        retry_count=getattr(getattr(source, "source", None), "retry_count", 0),
                        overwrite_invalidations=getattr(
                            getattr(source, "source", None), "overwrite_invalidations", 0),
                        **source.fit_snapshot,
                        trim_ms=getattr(getattr(session.probe, "config", None), "trim_ms", 0),
                        available_ms=max(0, (data["lead_p5_ms"] or 0)
                                         - (data["median_processing_ms"] or 0)))
        return dict(source="lms", state="off" if player.head_start_ms == 0 else "unavailable",
                    reason=("Head start is off" if player.head_start_ms == 0
                            else "Head start could not be verified; using delay instead"))

    def latency_status(self, config) -> dict:
        session = self._active
        airplay = any(player.type == VirtualPlayerType.AIRPLAY
                      and player.player_mac == config.player_mac
                      for player in self.storage.list_virtual_players())
        if session is None or session.latency_mac != config.player_mac:
            result = latency_status(config, delay=0)
        elif isinstance(session.probe, (AutoLatencyProbe, AirPlayAutoLatencyProbe)):
            result = session.probe.status()
        else:
            fallback = (config.strategy == "auto"
                        and isinstance(session.follower, LmsSyncGroupObserver))
            result = latency_status(
                config, state="not measurable (sync group)" if fallback else "idle",
                strategy="fixed" if fallback else config.strategy,
                delay=session.probe.current_delay_ms(),
                reason=("LMS reports a shared group position; using Fixed delay"
                        if fallback else None),
            )
            airplay = airplay or session.player_type == VirtualPlayerType.AIRPLAY
        if airplay and "source" not in result:
            result.update(source='airplay',
                          early_delivery_ms=installed_delivery_margin(self._SHAIRPORT_CONF),
                          median_processing_ms=None)
        if airplay:
            if (session is not None and session.latency_mac == config.player_mac
                    and session.player_type == VirtualPlayerType.AIRPLAY):
                data = self.airplay_timing.snapshot()
                result.update(audio_source=data["tap_source"],
                              lead_p5_ms=data["lead_p5_ms"],
                              lead_p50_ms=data["lead_p50_ms"],
                              tap_drop_count=data["tap_drop_count"],
                              median_processing_ms=data["median_processing_ms"])
            result["safety_message"] = self._airplay_safety_message
        if (session and session.player_type == VirtualPlayerType.LMS
                and session.latency_mac == config.player_mac
                and getattr(session, "lms_timed_source", None) is not None):
            timing = self.lms_timing
            if timing:
                result.update(timing)
        return result

    @property
    def timing_player_mac(self):
        if self._active and self._active.player_type == VirtualPlayerType.AIRPLAY:
            return self._active.profile.player_mac
        return self.follow_target_mac or self.detected_sync_master

    @property
    def timing_player_name(self):
        if self._active and self._active.player_type == VirtualPlayerType.AIRPLAY:
            return self._active.profile.display_name or self._active.profile.player_name
        return self.follow_target_name or self.detected_sync_master_name

    async def _apply_airplay_probe(self, session):
        mac = session.profile.player_mac
        config = self.storage.get_player_latency(mac)
        if config and config.strategy == 'auto':
            if isinstance(session.probe, AirPlayAutoLatencyProbe):
                session.probe.config = config
                margin = installed_delivery_margin(self._SHAIRPORT_CONF)
                if margin != session.probe.margin:
                    session.probe.margin = margin
                    session.probe.first = True
                    if margin == 0:
                        session.probe.delay = max(0, config.trim_ms)
                        session.probe.last_good = 0
                return
            def persist(measured, timestamp):
                current = self.storage.get_player_latency(mac)
                if current and current.strategy == 'auto':
                    current.measured_delay_ms = measured
                    current.measured_at = timestamp
                    self.storage.save_player_latency(current)
            probe = AirPlayAutoLatencyProbe(
                config, self.airplay_timing,
                installed_delivery_margin(self._SHAIRPORT_CONF), persist)
        elif config and config.strategy == 'fixed':
            probe = FixedLatencyProbe(config.fixed_delay_ms)
        else:
            probe = NoLatencyProbe()
        await session.probe.stop()
        await probe.start()
        session.probe = probe
        session.latency_mac = mac
        if session.sync_engine:
            session.sync_engine.update_probe(probe)

    async def _apply_probe_for_master(
        self, session: ActiveSession, master: str | None
    ) -> None:
        """Build the correct probe for *master* and install it on *session*."""
        profile = session.profile
        if master is None or master == profile.player_mac:
            # Standalone player or LampaStream is the sync master — no delay needed.
            new_probe: LatencyProbe = NoLatencyProbe()
            self.latency_warning = None
        else:
            pl = self.storage.get_player_latency(master)
            log.debug("PlayerLatency lookup for sync_master=%r -> %r", master, pl)
            if (pl is not None and pl.strategy == "auto"
                    and isinstance(session.probe, AutoLatencyProbe)
                    and session.latency_mac == master
                    and session.probe.follower is session.follower):
                # Trim/name edits preserve cadence, estimates and the first-step
                # allowance. The next sample applies trim through the normal limit.
                session.probe.config = pl
                self.latency_warning = None
                return
            if pl is None:
                self.latency_warning = (
                    f"Sync master {master} has no latency config — "
                    f"using 0 ms. Add it in the Player latency section."
                )
                new_probe = NoLatencyProbe()
            elif pl.strategy == "auto" and isinstance(session.follower, LmsSyncGroupObserver):
                new_probe = FixedLatencyProbe(pl.fixed_delay_ms)
                self.latency_warning = (
                    "Auto cannot measure a shared LMS sync-group position; using Fixed delay")
            elif pl.strategy == "auto" and session.follower is not None:
                def persist(measured, timestamp):
                    current = self.storage.get_player_latency(master)
                    if current is not None and current.strategy == "auto":
                        current.measured_delay_ms = measured
                        current.measured_at = timestamp
                        self.storage.save_player_latency(current)
                new_probe = AutoLatencyProbe(
                    pl, session.follower, persist, session.latency_preferences)
                self.latency_warning = None
            elif pl.strategy == "fixed":
                new_probe = FixedLatencyProbe(pl.fixed_delay_ms)
                self.latency_warning = None
            else:  # "none" or future strategies
                new_probe = NoLatencyProbe()
                self.latency_warning = None

        if getattr(session, "lms_timed_source", None) is not None:
            # Timed scenes use trim, not the legacy fixed-delay fallback. Retain
            # that probe's delay for insufficient-headroom mode only.
            new_probe.config = self.storage.get_player_latency(master) if master else None
            self.latency_warning = None
        old_probe = session.probe
        await old_probe.stop()
        session.latency_mac = master
        await new_probe.start()
        session.probe = new_probe
        if session.sync_engine:
            session.sync_engine.update_probe(new_probe)
        log.info(
            "Latency probe updated: sync_master=%s probe=%s delay_ms=%d",
            master,
            type(new_probe).__name__,
            new_probe.current_delay_ms(),
        )

    async def _poll_sync_master(self, session: ActiveSession) -> None:
        """Apply the latency probe for the followed player and fetch its display name.

        Runs once at Coupling activation — no periodic repeat.  Sending repeated
        status queries to the followed player (e.g. the Sonos Port via the
        sonos-squeezebox plugin) caused false newsong events every ~60 s, which
        restarted the Sonos audio stream.
        """
        profile = session.profile

        follow_mac: str | None = None
        if session.coupling:
            vp = self.storage.get_virtual_player(session.coupling.player_id)
            if vp:
                if vp.follow_mode == "sync_group":
                    return  # The session observer owns dynamic target/probe updates.
                follow_mac = vp.follow_player_mac or None

        lms_host = profile.lms_host
        if not lms_host:
            log.warning(
                "profile %r has no lms_host configured; "
                "attempting UDP discovery for latency probe",
                profile.name,
            )
            try:
                servers = await discover_lms(timeout=3.0)
                if servers:
                    lms_host = servers[0].host
                    log.info(
                        "LMS discovered at %s (%s) — using for latency probe; "
                        "set lms_host in the Virtual Player to avoid this",
                        lms_host, servers[0].name,
                    )
                else:
                    log.warning("LMS discovery found nothing; latency probe disabled")
                    return
            except Exception as exc:
                log.warning("LMS discovery failed (%s); latency probe disabled", exc)
                return

        if not follow_mac:
            log.warning(
                "Coupling %r has no follow_player_mac — "
                "no latency compensation applied. "
                "Set it in the Virtual Player editor.",
                profile.name,
            )
            self._detected_sync_master = None
            await self._apply_probe_for_master(session, None)
            if isinstance(session.track_source, LmsTrackPositionSource):
                try:
                    observed_at = time.monotonic()
                    status = await asyncio.to_thread(query_lms_status, lms_host, profile.player_mac)
                    session.track_source.seed(profile.player_mac, status, observed_at)
                except (OSError, ValueError):
                    pass  # subscription reconnects independently of initial availability
            return

        self._detected_sync_master = follow_mac
        try:
            observed_at = time.monotonic()
            master_status = await asyncio.to_thread(
                query_lms_status, lms_host, follow_mac
            )
            self._detected_sync_master_name = master_status.player_name
            if isinstance(session.track_source, LmsTrackPositionSource):
                session.track_source.seed(follow_mac, master_status, observed_at)
        except Exception as exc:
            log.debug("Could not fetch name for follow player %s: %s", follow_mac, exc)
            self._detected_sync_master_name = None
        await self._apply_probe_for_master(session, follow_mac)

    async def _diag_sync_both(
        self, label: str, lms_host: str, lampastream_mac: str, follow_mac: str | None
    ) -> None:
        """Log sync ? state for both players at a named checkpoint."""
        for name, mac in (("LampaStream", lampastream_mac), ("follow ", follow_mac)):
            if not mac:
                continue
            try:
                peers = await asyncio.to_thread(query_lms_sync_peers, lms_host, mac)
                log.info("DIAG [%s] %s (%s) sync? -> peers=%r", label, name, mac, peers)
            except Exception as exc:
                log.warning(
                    "DIAG [%s] %s (%s) sync? query failed: %s", label, name, mac, exc
                )

    async def _delayed_unsync_and_follow(
        self, session: ActiveSession, lms_host: str, player_mac: str
    ) -> None:
        """Wait for yeney-player to register with LMS, then unsync and start the follower.

        The 5-second delay ensures LMS recognises the player before the unsync
        command is sent.  Without it, the command silently no-ops because LMS
        has not yet seen the player's slimproto connection.
        """
        if not lms_host:
            log.warning(
                "LMS host not configured; skipping unsync and follower start. "
                "Set lms_host in the Virtual Player editor."
            )
            return

        follow_mac: str | None = None
        if session.coupling:
            vp = self.storage.get_virtual_player(session.coupling.player_id)
            if vp:
                follow_mac = vp.follow_player_mac or None

        await asyncio.sleep(5)

        # --- Diagnostic: check sync state BEFORE unsync on BOTH players ---
        await self._diag_sync_both("pre-unsync ", lms_host, player_mac, follow_mac)

        # --- Send the unsync command to LampaStream ---
        log.info("DIAG sending: %s sync -  (host=%s)", player_mac, lms_host)
        try:
            await asyncio.to_thread(unsync_player, lms_host, player_mac)
            log.info("DIAG unsync sent OK for %s", player_mac)
        except Exception as exc:
            log.warning("DIAG unsync failed for %s: %s", player_mac, exc)

        # --- Wait 3 s, then verify BOTH players are standalone ---
        await asyncio.sleep(3)
        await self._diag_sync_both("post-unsync", lms_host, player_mac, follow_mac)

        # --- Follower about to start — snapshot state right before ---
        await self._diag_sync_both("pre-follow ", lms_host, player_mac, follow_mac)

        if session.follower is not None:
            follower_task = session.follower.start()
            follower_task.add_done_callback(_log_task_failure)
            session.follower_task = follower_task

    _SHAIRPORT_CONF = Path("/usr/local/etc/shairport-sync.conf")

    async def _receiver_operation(self, operation, *args, **kwargs):
        # Do not leave a restart thread running after session teardown has returned.
        task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def _watch_airplay_delivery(self, session):
        while not session.stopping:
            await asyncio.sleep(0.5)
            await self._protect_airplay_delivery(session)

    async def _protect_airplay_delivery(self, session):
        """One rollback per manager lifetime; playback evidence survives pipe EOF."""
        if session.stopping or self._airplay_rollback_attempted:
            return
        if self.airplay_timing.snapshot()["stalled_for_s"] <= 3:
            return
        try:
            original = self._SHAIRPORT_CONF.read_text()
            if timing_settings(original).get("audio_backend_latency_offset_in_seconds", 0) >= 0:
                return
            updated = disable_early_delivery(original)
        except (OSError, ValueError) as exc:
            log.debug("Cannot inspect early delivery: %s", exc)
            return
        self._airplay_rollback_attempted = True
        cancelled = False
        try:
            # The existing receiver-name permission owns this file, not /usr/local/etc.
            # Validate before writing; restart only after the complete write is flushed.
            with self._SHAIRPORT_CONF.open("w") as output:
                output.write(updated)
                output.flush()
                os.fsync(output.fileno())
            await self._receiver_operation(
                subprocess.run, ["systemctl", "restart", "shairport-sync"],
                check=True, timeout=10, capture_output=True)
        except asyncio.CancelledError:
            cancelled = True  # restart completed; publish recovery before exiting the watchdog
        except (OSError, subprocess.SubprocessError) as exc:
            self._airplay_safety_message = "Early delivery recovery failed; check the receiver logs"
            self.latency_warning = self._airplay_safety_message
            log.error("Early delivery recovery failed (will not retry): %s", exc)
            return
        self._airplay_safety_message = (
            "Early delivery was too much for this sender and has been switched off")
        self.latency_warning = self._airplay_safety_message
        log.warning(self._airplay_safety_message)
        self.airplay_timing.reset("early delivery switched off")
        if self._airplay_tracks is not None:
            self._airplay_tracks.invalidate()
        if isinstance(session.probe, AirPlayAutoLatencyProbe):
            session.probe.margin = 0
            session.probe.delay = max(0, session.probe.config.trim_ms)
            session.probe.first = True
            session.probe.last_good = 0
        if cancelled:
            raise asyncio.CancelledError

    def _configure_shairport_name(self, name: str) -> bool:
        """Ensure shairport-sync is configured with the given advertised name.

        Return True only when configuration changed; unchanged receivers keep running.

        Existing operator settings are preserved. Only the receiver name changes,
        through a validated update; missing files receive defaults. The service owns
        the file, but does not have permission to replace its parent directory.
        shairport-sync reads its name at startup, so a restart is required.
        """
        conf = (
            'general = {\n'
            '  name = "LampaStream";\n'
            '  output_backend = "pipe";\n'
            '  // Analysis-only receiver: full-scale PCM regardless of source volume.\n'
            '  ignore_volume_control = "yes";\n'
            '}\n'
            'pipe = {\n'
            '  name = "/run/lampastream/airplay.pcm";\n'
            '  output_rate = 44100;\n'
            '  output_format = "S16_LE";\n'
            '  output_channels = 2;\n'
            '}\n'
            'metadata = {\n'
            '  enabled = "yes";\n'
            '  include_cover_art = "yes";\n'
            '  pipe_name = "/run/lampastream/airplay.metadata";\n'
            '  progress_interval = 10.0;\n'
            '}\n'
        )
        conf = rename_receiver(conf, name)
        try:
            existing = self._SHAIRPORT_CONF.read_text()
        except OSError:
            existing = None
        if existing is not None:
            try:
                conf = rename_receiver(existing, name)
            except ValueError as exc:
                log.warning("Could not safely update receiver name: %s", exc)
                raise RuntimeError("Cannot safely configure the AirPlay receiver") from exc
        changed = existing != conf
        try:
            if changed:
                self._SHAIRPORT_CONF.write_text(conf)
            active = subprocess.run(
                ["systemctl", "is-active", "shairport-sync"],
                timeout=10, capture_output=True, text=True,
            ).returncode == 0
            if not active:
                subprocess.run(["systemctl", "start", "shairport-sync"],
                               check=True, timeout=10, capture_output=True)
                log.info("AirPlay receiver started (service was inactive)")
            elif changed:
                log.warning("AirPlay receiver name changed; "
                            "any connected sender will be interrupted")
                subprocess.run(["systemctl", "restart", "shairport-sync"],
                               check=True, timeout=10, capture_output=True)
                log.info("shairport-sync restarted with name %r", name)
            else:
                log.info("AirPlay receiver kept running (configuration unchanged)")
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Cannot prepare the AirPlay receiver") from exc
        return changed

    def _start_lms_player(self, session: ActiveSession, profile: Profile) -> None:
        # yeney-core implements both the legacy CAVA prefix and SHM v1 extension.
        name = "yeney-player"
        binary = shutil.which(name)
        if not binary:
            raise RuntimeError(f"{name} binary not found; run scripts/install-lampastream.sh")

        if not profile.player_mac:
            profile.player_mac = generate_locally_administered_mac()
            if session.coupling:
                player = self.storage.get_virtual_player(session.coupling.player_id)
                if player:
                    player.player_mac = profile.player_mac
                    self.storage.save_virtual_player(player)
            log.info(
                "Generated missing player_mac %s for %s",
                profile.player_mac, profile.name,
            )

        cmd = [
            binary,
            "-n", profile.display_name or profile.player_name,
            "-m", profile.player_mac,
            "-v",
        ]
        # Compatibility only: yeney-player accepts and ignores this device.
        if profile.alsa_device:
            cmd += ["-o", profile.alsa_device]
        # Pass only the host address, never a port.  yeney-player's -s flag
        # expects the slimproto port (3483); profile.lms_port is the LMS
        # web/JSON-RPC port (typically 9000) and must not be passed here.
        # Without an explicit port yeney-player connects to 3483 by default.
        # Without -s at all it falls back to UDP broadcast discovery.
        if profile.lms_host:
            cmd += ["-s", profile.lms_host]
        session.lms_player = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def _wait_for_shm(self, mac: str, timeout: float = 10.0, interval: float = 0.1) -> None:
        """Wait until yeney-player's shared-memory segment appears in /dev/shm.

        yeney-player creates /dev/shm/squeezelite-<mac> a moment after it
        starts. Wait before opening the canonical PCM reader.
        """
        path = Path(f"/dev/shm/squeezelite-{mac}")
        deadline = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Timed out waiting for yeney-player shared-memory segment {path}"
                )
            time.sleep(interval)
        log.debug("yeney-player SHM segment ready: %s", path)
