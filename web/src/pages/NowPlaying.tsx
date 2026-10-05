import { LightsRow } from '@/components/LightsRow'
import { MusicChoices } from '@/components/MusicChoices'
import { LightTiming } from '@/components/LightTiming'
import { LiveEnergySource } from '@/components/LiveEnergySource'
import { TrackProgress } from '@/components/TrackProgress'
import { ChevronRight } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { ColourSwatch } from '@/components/ColourSwatch'
import { FloorplanPreview } from '@/components/FloorplanPreview'
import { SpectrumBars } from '@/components/SpectrumBars'
import { SliderField } from '@/components/SliderField'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import type { PreviewState, SocketStatus } from '@/hooks/usePreviewSocket'
import {
  type Analyser,
  type EnergyProfile,
  getEnergyProfiles,
  getEffects,
  type Effect,
  SPECTRUM_BACKEND_OPTIONS,
  ONSET_METHODS,
  type VirtualPlayer,
  getAnalysers,
  getVirtualPlayers,
  type ChannelPosition,
  type Coupling,
  activateCoupling,
  deactivateCoupling,
  getCouplings,
  getZoneChannels,
  restartCouplingCava,
  updateAnalyser,
} from '@/lib/api'

const LOG_MIN = Math.log10(20)
const LOG_MAX = Math.log10(20000)

const DEFAULT_LOW  = 50
const DEFAULT_HIGH = 12000
const DEFAULT_BASS = 250
const DEFAULT_MID  = 2000

function hzToSlider(hz: number): number {
  return (Math.log10(Math.max(hz, 20)) - LOG_MIN) / (LOG_MAX - LOG_MIN) * 100
}

function sliderToHz(v: number): number {
  return Math.round(10 ** (LOG_MIN + v / 100 * (LOG_MAX - LOG_MIN)))
}

function StatusRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </>
  )
}

function StatusGrid({ status, analyser, effects, profile, manual, onOpen }: {
  status: SocketStatus | null
  analyser?: Analyser
  effects: Effect[]; profile?: EnergyProfile; manual: boolean; onOpen?: (id: string) => void
  playerType?: string | null
}) {
  const matchingEffects = effects.filter(item => item.effect_type === status?.effect_type)
  const effect = effects.find(item => item.id === profile?.high_energy_effect_id)
    ?? effects.find(item => item.id === status?.effect_type)
    ?? (matchingEffects.length === 1 ? matchingEffects[0] : undefined)
  const unknown = <span className="text-muted-foreground">—</span>
  return (
    <dl aria-label="Session status" className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm items-start [&_dd]:min-w-0 [&_dd]:break-words">
      <StatusRow label="Spectrum engine">
        {SPECTRUM_BACKEND_OPTIONS.find(option => option.value === analyser?.spectrum_backend)?.label ?? unknown}
      </StatusRow>
      <StatusRow label="Beat detection">
        {ONSET_METHODS.find(option => option.value === analyser?.onset_method)?.label ?? unknown}
      </StatusRow>
      <StatusRow label="Effect">
        {effect ? <span title={status?.effect_type ?? effect.id}>{effect.name}</span> : unknown}
      </StatusRow>
      <StatusRow label="Energy profile">
        {profile?.name ?? unknown}
        {manual && <span className="ml-2 text-xs text-muted-foreground">Manual choice active</span>}
      </StatusRow>
      {profile && <dd className="col-span-2 mt-2"><a className="text-primary hover:underline underline-offset-2" href={`#energy-profiles/${encodeURIComponent(profile.id)}`}
        onClick={event => { if (onOpen) { event.preventDefault(); onOpen(profile.id) } }}>Open Energy Profile ›</a></dd>}
    </dl>
  )
}

function SessionDiagnostics({ status, playerType }: {
  status: SocketStatus | null
  playerType?: string | null
}) {
  if (!status) return null
  const indicator = (ok: boolean, text: string) => <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
    <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${ok ? 'bg-green-500' : 'bg-amber-500'}`} />{text}
  </span>
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-testid="session-diagnostics">
    {indicator(status.bridge_connected, status.bridge_connected ? 'Bridge connected' : 'Bridge disconnected')}
    {playerType === 'LMS' && indicator(status.processes.lms_player, status.processes.lms_player ? 'LMS player running' : 'LMS player stopped')}
    {playerType === 'AirPlay' && indicator(status.airplay_receiving === true,
      status.airplay_receiving === true ? 'AirPlay receiving audio' : status.airplay_receiving === false ? 'Waiting for AirPlay connection…' : 'AirPlay —')}
    {status.follower_warning && <p className="w-full text-destructive text-xs">{status.follower_warning}</p>}
    {status.latency_warning && <p className="w-full text-destructive text-xs">{status.latency_warning}</p>}
  </div>
}

function CouplingSelector({
  couplings,
  status,
  onChanged,
}: {
  status: SocketStatus | null
  couplings: Coupling[]
  onChanged: () => void
}) {
  const [selected, setSelected] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // When couplings load and one is already active, pre-select it.
  useEffect(() => {
    if (!selected && status?.active_coupling_id) {
      setSelected(status.active_coupling_id)
    }
  }, [status?.active_coupling_id, couplings, selected])

  const isActive = !!status?.active_coupling_id
  const selectedIsActive = status?.active_coupling_id === selected

  async function handleActivate() {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      await activateCoupling(selected)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    setBusy(true)
    setError(null)
    try {
      await deactivateCoupling()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">
          Active coupling
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3">
          <select
            className="min-w-0 flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={busy}
          >
            <option value="">— select a coupling —</option>
            {couplings.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>

          <Button
            size="sm"
            onClick={handleActivate}
            disabled={busy || !selected || selectedIsActive}
          >
            {busy && !isActive ? 'Starting…' : 'Go'}
          </Button>

          {isActive && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleStop}
              disabled={busy}
            >
              {busy && isActive ? 'Stopping…' : 'Stop'}
            </Button>
          )}
        </div>

        <p className="text-xs text-muted-foreground italic leading-snug">
          Switching couplings restarts the full session (LMS player, analysis,
          DTLS) and resets the BandNormaliser EMA. For a live A/B comparison,
          swap the active coupling's Analyser or Energy Profile instead —
          those update without a session restart.
        </p>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  )
}

type Props = Pick<PreviewState, 'colour' | 'channel_colours' | 'onset' | 'bars' | 'status'> & {
  expertMode?: boolean
  onOpenLatency?: () => void
  onOpenEffect?: (id: string) => void
  onOpenEnergyProfile?: (id: string) => void
  last_energy_input?: number
  normalised_bars?: number[]
  onset_bass?: boolean
  onset_mid?: boolean
  onset_treble?: boolean
  sustained_energy?: number | null
  mix?: number
  loudness_momentary_lufs?: number | null
  connected?: boolean
}

export function NowPlaying({ expertMode = false, colour, channel_colours, onset, onset_bass = false, onset_mid = false, onset_treble = false, mix = 0, sustained_energy = null, loudness_momentary_lufs = null, bars, normalised_bars, status, connected = true, onOpenLatency, onOpenEffect, onOpenEnergyProfile, last_energy_input = 0 }: Props) {
  const couplingId = status?.active_coupling_id ?? null
  const zoneId = status?.active_zone_id ?? null

  const initializedForRef = useRef<string | null>(null)
  const [channels, setChannels] = useState<ChannelPosition[]>([])

  // Fetch channel positions whenever the active zone changes.
  useEffect(() => {
    if (!zoneId) {
      setChannels([])
      return
    }
    getZoneChannels(zoneId).then(setChannels).catch(() => setChannels([]))
  }, [zoneId])

  const [lowSlider, setLowSlider] = useState<number>(hzToSlider(50))
  const [highSlider, setHighSlider] = useState<number>(hzToSlider(12000))
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<string | null>(null)
  const [applyError, setApplyError] = useState(false)

  const [bassSlider, setBassSlider] = useState<number>(hzToSlider(250))
  const [midSlider, setMidSlider] = useState<number>(hzToSlider(2000))
  const tuningId = useId()
  const [tuningOpen, setTuningOpen] = useState(() => {
    try { return localStorage.getItem('lampastream.spectrumTuning') === '1' }
    catch { return false }
  })
  const [normaliserBusy, setNormaliserBusy] = useState(false)
  const normaliserPending = useRef(false)
  const [normaliserError, setNormaliserError] = useState<string | null>(null)

  // Reload coupling selector when activation changes.
  const [reloadKey, setReloadKey] = useState(0)
  const [couplings, setCouplings] = useState<Coupling[]>([])
  const [analysers, setAnalysers] = useState<Analyser[]>([])
  const [effects, setEffects] = useState<Effect[]>([])
  const [energyProfiles, setEnergyProfiles] = useState<EnergyProfile[]>([])
  const [players, setPlayers] = useState<VirtualPlayer[]>([])
  useEffect(() => {
    let cancelled = false
    getCouplings().then((items) => { if (!cancelled) setCouplings(items) }).catch(() => {})
    getAnalysers().then((items) => { if (!cancelled) setAnalysers(items) }).catch(() => {})
    getEffects().then((items) => { if (!cancelled) setEffects(items) }).catch(() => {})
    getEnergyProfiles().then((items) => { if (!cancelled) setEnergyProfiles(items) }).catch(() => {})
    getVirtualPlayers().then((items) => { if (!cancelled) setPlayers(items) }).catch(() => {})
    return () => { cancelled = true }
  }, [reloadKey, couplingId, status?.active_energy_profile_id])
  const activeCoupling = couplings.find((item) => item.id === couplingId)
  const activeEnergyProfile = couplingId ? energyProfiles.find(item => item.id === status?.active_energy_profile_id) : undefined
  const activeAnalyser = analysers.find((item) => item.id === activeCoupling?.analyser_id)
  const normaliserOn = !!couplingId && !!activeAnalyser?.band_normalise
  const playerType = status?.active_player_type ?? players.find((item) => item.id === activeCoupling?.player_id)?.type


  useEffect(() => {
    if (!couplingId || couplingId === initializedForRef.current) return
    if (!status) return
    initializedForRef.current = couplingId
    if (status.lower_cutoff_freq != null) setLowSlider(hzToSlider(status.lower_cutoff_freq))
    if (status.higher_cutoff_freq != null) setHighSlider(hzToSlider(status.higher_cutoff_freq))
    if (status.bass_hz != null) setBassSlider(hzToSlider(status.bass_hz))
    if (status.mid_hz != null) setMidSlider(hzToSlider(status.mid_hz))
    setApplyResult(null)
  }, [couplingId, status])

  const appliedLower  = status?.lower_cutoff_freq  ?? 50
  const appliedHigher = status?.higher_cutoff_freq ?? 12000
  const appliedBass   = status?.bass_hz            ?? 250
  const appliedMid    = status?.mid_hz             ?? 2000

  const pendingLower  = sliderToHz(lowSlider)
  const pendingHigher = sliderToHz(highSlider)
  const pendingBass   = sliderToHz(bassSlider)
  const pendingMid    = sliderToHz(midSlider)

  const hasChanges            = pendingLower !== appliedLower || pendingHigher !== appliedHigher
  const hasBandChanges        = pendingBass  !== appliedBass  || pendingMid    !== appliedMid
  const hasDefaultChanges     = pendingLower !== DEFAULT_LOW  || pendingHigher !== DEFAULT_HIGH
  const hasDefaultBandChanges = pendingBass  !== DEFAULT_BASS || pendingMid    !== DEFAULT_MID

  function handleBassChange(v: number) {
    const hz = sliderToHz(v)
    if (hz >= pendingMid) return
    if (hz <= appliedLower) return
    setBassSlider(v)
  }

  function handleMidChange(v: number) {
    const hz = sliderToHz(v)
    if (hz <= pendingBass) return
    if (hz >= appliedHigher) return
    setMidSlider(v)
  }

  function handleLowCommit(hz: number) {
    setLowSlider(hzToSlider(Math.max(20, Math.min(pendingHigher - 1, hz))))
  }

  function handleHighCommit(hz: number) {
    setHighSlider(hzToSlider(Math.max(pendingLower + 1, Math.min(20000, hz))))
  }

  function handleBassCommit(hz: number) {
    const constrained = Math.max(appliedLower + 1, Math.min(pendingMid - 1, hz))
    setBassSlider(hzToSlider(constrained))
  }

  function handleMidCommit(hz: number) {
    const constrained = Math.max(pendingBass + 1, Math.min(appliedHigher - 1, hz))
    setMidSlider(hzToSlider(constrained))
  }

  async function handleApply() {
    if (!couplingId) return
    setApplying(true)
    setApplyResult(null)
    setApplyError(false)
    try {
      await restartCouplingCava(couplingId, { lower_cutoff_freq: pendingLower, higher_cutoff_freq: pendingHigher, bass_hz: pendingBass, mid_hz: pendingMid })
      setApplyResult('Applied.')
    } catch (e) {
      setApplyResult(e instanceof Error ? e.message : 'Failed')
      setApplyError(true)
    } finally {
      setApplying(false)
    }
  }

  function handleReset() {
    setLowSlider(hzToSlider(appliedLower))
    setHighSlider(hzToSlider(appliedHigher))
    handleResetBands()
  }

  function handleRestoreDefaults() {
    setLowSlider(hzToSlider(DEFAULT_LOW))
    setHighSlider(hzToSlider(DEFAULT_HIGH))
    handleRestoreDefaultsBands()
  }

  function handleResetBands() {
    setBassSlider(hzToSlider(appliedBass))
    setMidSlider(hzToSlider(appliedMid))
  }

  function handleRestoreDefaultsBands() {
    setBassSlider(hzToSlider(DEFAULT_BASS))
    setMidSlider(hzToSlider(DEFAULT_MID))
  }

  async function toggleNormaliser() {
    if (!couplingId || !activeAnalyser || normaliserPending.current) return
    const id = activeAnalyser.id
    const previous = !!activeAnalyser.band_normalise
    const next = !previous
    normaliserPending.current = true
    setNormaliserBusy(true)
    setNormaliserError(null)
    setAnalysers(items => items.map(item => item.id === id ? { ...item, band_normalise: next } : item))
    try {
      const updated = await updateAnalyser(id, { band_normalise: next })
      setAnalysers(items => items.map(item => item.id === id
        ? { ...item, band_normalise: updated.band_normalise ?? next } : item))
    } catch (error) {
      setAnalysers(items => items.map(item => item.id === id ? { ...item, band_normalise: previous } : item))
      setNormaliserError(error instanceof Error ? error.message : 'Could not change the band normaliser')
    } finally {
      normaliserPending.current = false
      setNormaliserBusy(false)
    }
  }

  function toggleTuning() {
    const next = !tuningOpen
    setTuningOpen(next)
    try { localStorage.setItem('lampastream.spectrumTuning', next ? '1' : '0') }
    catch { /* Browser storage may be unavailable. */ }
  }

  const frequencyLabel = (hz: number) => hz >= 1000 ? `${Math.round(hz / 100) / 10} kHz` : `${hz} Hz`

  return (
    <div className="space-y-4">
      <CouplingSelector
        key={reloadKey}
        couplings={couplings}
        status={status}
        onChanged={() => setReloadKey((k) => k + 1)}
      />

      <TrackProgress track={status?.track ?? null} connected={connected}
        showControls={playerType !== 'AirPlay'}
        transport={playerType === 'LMS' && couplingId && status?.follow_target_mac ? {
          couplingId, targetMac: status.follow_target_mac, targetName: status.follow_target_name || status.follow_target_mac,
        } : undefined} />

      {status?.active_coupling_id && <LightsRow key={status.active_coupling_id}
        couplingId={status.active_coupling_id} output={status.output_status} />}

      <LightTiming status={status} onOpenLatency={onOpenLatency} />

      <Card data-testid="live-preview-card">
        <CardHeader className="pb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
          <CardTitle className="text-base">Live preview</CardTitle>
          <SessionDiagnostics status={status} playerType={playerType} />
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,11fr)_minmax(0,9fr)] gap-6 items-stretch" data-testid="live-preview-grid">
            <section className="min-w-0 rounded-xl border p-4" aria-label="Lights preview">
              <div className="mb-3 flex items-center justify-between gap-3 text-sm text-muted-foreground">
                <h3 title="An onset appears as a white outline on the floorplan">Lights</h3>
                <ColourSwatch r={colour.r} g={colour.g} b={colour.b} />
              </div>
              <div className="w-full" data-testid="floorplan-preview-size">
                <FloorplanPreview channels={channels} colours={channel_colours} onset={onset} />
              </div>
            </section>
            <section className="min-w-0 rounded-xl border p-4" aria-label="Analysis">
              <h3 className="mb-4 text-sm text-muted-foreground">Analysis</h3>
              <StatusGrid status={status} analyser={activeAnalyser} effects={effects} profile={activeEnergyProfile}
                manual={!!couplingId && (status?.music?.manual ?? !!(activeCoupling?.manual_energy_profile_id || activeCoupling?.manual_palette_id))} onOpen={onOpenEnergyProfile} />
            </section>
          </div>
          <LiveEnergySource expertMode={expertMode} profile={activeEnergyProfile} active={!!couplingId}
            effects={effects} onOpenEffect={onOpenEffect}
            gauge={<div data-testid="energy-blend">
              <div className="mb-3 flex items-center justify-between gap-4">
                <span className="text-sm text-muted-foreground">Blend between low and high energy effect</span>
                <span className="text-3xl font-semibold tabular-nums">{Math.round(mix * 100)}%</span>
              </div>
              <div className="relative h-2 w-full overflow-hidden rounded-full bg-secondary">
                <div data-testid="energy-input-marker" title={`Energy input: ${Math.round(last_energy_input * 100)}%`} className="absolute z-10 h-full w-0.5 bg-foreground" style={{ left: `${Math.max(0, Math.min(1, last_energy_input)) * 100}%` }} />
                <div className="h-full bg-foreground transition-none" style={{ width: `${mix * 100}%` }}
                  title={`High-energy Effect: ${Math.round(mix * 100)}% (Low energy: ${Math.round((1 - mix) * 100)}%)`} />
              </div>
            </div>}
            readouts={<div className="my-5 grid grid-cols-2 gap-4 sm:flex sm:gap-8">
              <div><div className="mb-1 text-xs text-muted-foreground">Sustained energy</div>
                <span className="tabular-nums" data-testid="sustained-energy">{connected && sustained_energy !== null && Number.isFinite(sustained_energy) ? sustained_energy.toFixed(2) : '—'}</span></div>
              <div><div className="mb-1 text-xs text-muted-foreground">Momentary loudness</div>
                <span className="tabular-nums" title="K-weighted momentary loudness (400 ms); independent of energy blend" data-testid="momentary-loudness">{connected && loudness_momentary_lufs !== null && Number.isFinite(loudness_momentary_lufs) ? `${loudness_momentary_lufs.toFixed(1)} LUFS` : '— LUFS'}</span></div>
            </div>}
            onUpdated={updated => setEnergyProfiles(items => items.map(item => item.id === updated.id ? updated : item))} />
        </CardContent>
      </Card>

      <Card data-testid="spectrum-panel">
        <CardHeader className="pb-3">
          <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">Spectrum</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <SpectrumBars
            bars={bars}
            normalisedBars={normaliserOn ? normalised_bars : undefined}
            colorMode={status?.effect_type ?? null}
            lowerCutoffHz={appliedLower}
            higherCutoffHz={appliedHigher}
            bassHz={appliedBass}
            midHz={appliedMid}
            onsetBass={onset_bass}
            onsetMid={onset_mid}
            onsetTreble={onset_treble}
          />
          {normaliserOn && normalised_bars?.length === bars.length && bars.length > 0 && (
            <div className="flex gap-3 text-xs text-muted-foreground" data-testid="spectrum-legend">
              <span className="flex items-center gap-1"><span className="h-2 w-2 bg-current" />Raw</span>
              <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded-full bg-current" />Normalised</span>
            </div>
          )}
          <Separator />
          <div className="flex min-h-11 items-center justify-between gap-3">
            <div className="min-w-0">
              <label id={`${tuningId}-normaliser-label`} htmlFor={`${tuningId}-normaliser`} className="text-sm">Band normaliser</label>
              <p id={`${tuningId}-normaliser-help`} className="text-xs text-muted-foreground">
                {couplingId ? `Balances bass, mid and treble colours · Analyser "${activeAnalyser?.name ?? '—'}"`
                  : 'Start a coupling to change this'}
              </p>
            </div>
            <button id={`${tuningId}-normaliser`} type="button" role="switch" aria-checked={normaliserOn}
              aria-labelledby={`${tuningId}-normaliser-label`} aria-describedby={`${tuningId}-normaliser-help`}
              aria-busy={normaliserBusy} disabled={!couplingId || !activeAnalyser || normaliserBusy}
              onClick={toggleNormaliser}
              className="flex min-h-11 min-w-14 shrink-0 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              <span aria-hidden="true" className={`flex h-7 w-12 items-center rounded-full border p-0.5 ${normaliserOn ? 'justify-end bg-emerald-600 dark:bg-emerald-500' : 'justify-start bg-muted'}`}>
                <span className="h-5 w-5 rounded-full bg-white shadow-sm" />
              </span>
            </button>
          </div>
          {couplingId && normaliserError && <p role="alert" className="text-sm text-destructive">{normaliserError}</p>}
          {couplingId && <>
            <Separator />
            <button type="button" aria-expanded={tuningOpen} aria-controls={tuningId} onClick={toggleTuning}
              className="flex min-h-11 w-full flex-wrap items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="flex min-w-0 items-center gap-2">
                <ChevronRight aria-hidden="true" className={`h-4 w-4 shrink-0 ${tuningOpen ? 'rotate-90' : ''}`} />
                <span className="text-sm">Frequency range and bands</span>
              </span>
              {!tuningOpen && <span className="ml-auto text-xs text-muted-foreground">
                {frequencyLabel(appliedLower)} – {frequencyLabel(appliedHigher)} · {frequencyLabel(appliedBass)} · {frequencyLabel(appliedMid)}
              </span>}
            </button>
            <div id={tuningId} hidden={!tuningOpen} className="space-y-4">
              {[
                { title: 'Frequency cutoffs', fields: [
                  { label: 'Low cut', value: lowSlider, hz: pendingLower, change: setLowSlider, commit: handleLowCommit, id: 'low-cut-hz' },
                  { label: 'High cut', value: highSlider, hz: pendingHigher, change: setHighSlider, commit: handleHighCommit, id: 'high-cut-hz' },
                ] },
                { title: 'Band boundaries', fields: [
                  { label: 'Bass / mid', value: bassSlider, hz: pendingBass, change: handleBassChange, commit: handleBassCommit, id: 'bass-hz' },
                  { label: 'Mid / treble', value: midSlider, hz: pendingMid, change: handleMidChange, commit: handleMidCommit, id: 'mid-hz' },
                ] },
              ].map(group => <div key={group.title} className="space-y-3">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{group.title}</p>
                {group.fields.map(field => <SliderField key={field.id} label={field.label}
                  value={field.value} min={0} max={100} step={1} format={() => `${field.hz} Hz`}
                  onChange={field.change} disabled={applying} inputHz={field.hz}
                  inputMin={20} inputMax={20000} onInputCommit={field.commit} inputTestId={field.id} />)}
              </div>)}
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" onClick={handleApply} disabled={applying || (!hasChanges && !hasBandChanges)} data-testid="apply-cutoffs">
                  {applying ? 'Applying…' : 'Apply'}
                </Button>
                <Button size="sm" variant="outline" onClick={handleReset}
                  disabled={applying || (!hasChanges && !hasBandChanges)} title="Reset to saved value" data-testid="reset-cutoffs">
                  Reset to saved
                </Button>
                <Button size="sm" variant="ghost" onClick={handleRestoreDefaults}
                  disabled={applying || (!hasDefaultChanges && !hasDefaultBandChanges)} title="Restore factory defaults" data-testid="restore-defaults-cutoffs">
                  Restore defaults
                </Button>
                {applyResult && <span className={applyError ? 'text-destructive text-sm' : 'text-sm text-muted-foreground'}>{applyResult}</span>}
                <span className="ml-auto text-xs italic text-muted-foreground">analysis restarts briefly</span>
              </div>
            </div>
          </>}
        </CardContent>
      </Card>

      {status?.music && <MusicChoices music={status.music} coupling={activeCoupling} profiles={energyProfiles} />}

    </div>
  )
}
