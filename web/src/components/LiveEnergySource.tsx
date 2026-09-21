import { useEffect, useRef, useState } from 'react'
import { EnergySourceControls, validateEnergySettings, type EnergySetting } from './EnergyBlendEditor'
import { updateEnergyProfile, type EnergyProfile } from '@/lib/api'

export function LiveEnergySource({ profile, active, expertMode = false, onUpdated, onOpen }: {
  profile?: EnergyProfile; active: boolean; expertMode?: boolean
  onUpdated: (profile: EnergyProfile) => void; onOpen?: (id: string) => void
}) {
  const values = () => ({ floor: String(profile?.lufs_floor ?? -30), ceiling: String(profile?.lufs_ceiling ?? -8), tau: String(profile?.adaptation_tau_s ?? 60), attack: String(profile?.peak_attack_s ?? 0.05), release: String(profile?.peak_release_s ?? 2), reshapePower: String(profile?.peak_reshape_power ?? 0.4) })
  const [draft, setDraft] = useState(values)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const stepTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const cancelStep = () => { clearTimeout(stepTimer.current); stepTimer.current = undefined }
  useEffect(() => cancelStep, [])
  useEffect(() => { cancelStep(); setDraft(values()); setError(null) }, [profile, expertMode])

  async function patch(body: Partial<EnergyProfile>) {
    if (!expertMode || !active || !profile || pending.current) return
    pending.current = true; setBusy(true); setError(null)
    try { onUpdated(await updateEnergyProfile(profile.id, body)) }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to update energy profile') }
    finally { pending.current = false; setBusy(false) }
  }
  function change(field: EnergySetting, value: string) {
    cancelStep()
    if (field === 'energy_source') {
      if (value !== (profile?.energy_source ?? 'sustained')) void patch({ energy_source: value })
    } else if (field === 'peak_reshape_enabled') {
      void patch({ peak_reshape_enabled: value === 'true' })
    } else if (field === 'peak_envelope_auto') {
      void patch({ peak_envelope_auto: value === 'true' })
    } else {
      const key = draftKey(field)
      setDraft(d => ({ ...d, [key]: value }))
    }
  }
  function commit(next = draft) {
    cancelStep()
    if (!profile || validateEnergySettings({ ...next, source: profile.energy_source ?? 'sustained', peakAuto: profile.peak_envelope_auto ?? true, reshapeEnabled: profile.peak_reshape_enabled ?? false })) return
    const body: Partial<EnergyProfile> = {}
    if (profile.energy_source === 'loudness_fixed') {
      if (Number(next.floor) !== (profile.lufs_floor ?? -30)) body.lufs_floor = Number(next.floor)
      if (Number(next.ceiling) !== (profile.lufs_ceiling ?? -8)) body.lufs_ceiling = Number(next.ceiling)
    } else if (profile.energy_source === 'loudness_adaptive' && Number(next.tau) !== (profile.adaptation_tau_s ?? 60)) body.adaptation_tau_s = Number(next.tau)
    if (profile.energy_source === 'peak_envelope' && profile.peak_envelope_auto === false) {
      if (Number(next.attack) !== (profile.peak_attack_s ?? 0.05)) body.peak_attack_s = Number(next.attack)
      if (Number(next.release) !== (profile.peak_release_s ?? 2)) body.peak_release_s = Number(next.release)
    }
    if (profile.energy_source === 'peak_envelope' && profile.peak_reshape_enabled) {
      if (Number(next.reshapePower) !== (profile.peak_reshape_power ?? 0.4)) body.peak_reshape_power = Number(next.reshapePower)
    }
    if (Object.keys(body).length) void patch(body)
  }
  function step(field: EnergySetting, value: string) {
    const key = draftKey(field)
    const next = { ...draft, [key]: value }
    cancelStep(); setDraft(next)
    stepTimer.current = setTimeout(() => commit(next), 250)
  }
  const header = <div className="min-w-0 text-xs text-muted-foreground">
    <span>Energy profile </span><span className="text-foreground">{active ? profile?.name ?? '—' : '—'}</span>
    {active && profile && <> · <a href={`#energy-profiles/${encodeURIComponent(profile.id)}`}
      onClick={e => { if (onOpen) { e.preventDefault(); onOpen(profile.id) } }}
      className="text-primary hover:underline underline-offset-2">Open profile</a></>}
  </div>
  return <div className="mt-3" data-testid="live-energy-source">
    {expertMode ? <EnergySourceControls compact header={header} source={profile?.energy_source ?? 'sustained'}
      floor={draft.floor} ceiling={draft.ceiling} tau={draft.tau} onChange={change}
      peakAuto={profile?.peak_envelope_auto ?? true} attack={draft.attack} release={draft.release}
      reshapeEnabled={profile?.peak_reshape_enabled ?? false} reshapePower={draft.reshapePower}
      onCommit={() => commit()} onStep={step} disabled={!active || !profile} pending={busy} /> : header}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </div>
}

function draftKey(field: EnergySetting) {
  return field === 'lufs_floor' ? 'floor' : field === 'lufs_ceiling' ? 'ceiling'
    : field === 'peak_reshape_power' ? 'reshapePower' : field === 'peak_attack_s' ? 'attack' : field === 'peak_release_s' ? 'release' : 'tau'
}
