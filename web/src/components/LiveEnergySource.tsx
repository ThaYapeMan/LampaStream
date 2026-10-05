import { useEffect, useRef, useState, type ReactNode } from 'react'
import { EnergySourceControls, validateEnergySettings, type EnergySetting } from './EnergyBlendEditor'
import { updateEnergyProfile, type EnergyProfile, type Effect } from '@/lib/api'

export function LiveEnergySource({ profile, active, expertMode = false, onUpdated, effects = [], onOpenEffect, gauge, readouts }: {
  gauge?: ReactNode; readouts?: ReactNode
  effects?: Effect[]; onOpenEffect?: (id: string) => void
  profile?: EnergyProfile; active: boolean; expertMode?: boolean
  onUpdated: (profile: EnergyProfile) => void
}) {
  const values = () => ({ floor: String(profile?.lufs_floor ?? -30), ceiling: String(profile?.lufs_ceiling ?? -8), tau: String(profile?.adaptation_tau_s ?? 60), attack: String(profile?.peak_attack_s ?? 0.05), release: String(profile?.peak_release_s ?? 2), reshapePower: String(profile?.peak_reshape_power ?? 0.4) })
  const [draft, setDraft] = useState(values)
  const [error, setError] = useState<string | null>(null)
  const [lastSources, setLastSources] = useState<Record<string, string>>({})
  const [optimistic, setOptimistic] = useState<{ id: string; source: string } | null>(null)
  const source = optimistic && optimistic.id === profile?.id ? optimistic.source : profile?.energy_source ?? 'sustained'
  useEffect(() => {
    if (profile && profile.energy_source !== 'off') setLastSources(items => ({ ...items, [profile.id]: profile.energy_source ?? 'sustained' }))
  }, [profile?.id, profile?.energy_source])
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const stepTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const cancelStep = () => { clearTimeout(stepTimer.current); stepTimer.current = undefined }
  useEffect(() => cancelStep, [])
  useEffect(() => { cancelStep(); setDraft(values()); setError(null) }, [profile, expertMode])

  async function patch(body: Partial<EnergyProfile>) {
    if (!expertMode || !active || !profile || pending.current) return
    if (body.energy_source) {
      if (source !== 'off') setLastSources(items => ({ ...items, [profile.id]: source }))
      setOptimistic({ id: profile.id, source: body.energy_source })
    }
    pending.current = true; setBusy(true); setError(null)
    try { onUpdated(await updateEnergyProfile(profile.id, body)) }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to update energy profile') }
    finally { setOptimistic(null); pending.current = false; setBusy(false) }
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
  const reason = !active ? 'No active coupling' : !profile ? 'No energy profile available' : undefined
  return <section className="mt-6 border-t pt-5" data-testid="live-energy-source" aria-label="Energy">
    <div className="mb-5 flex items-center justify-between gap-3">
      <h3 className="text-base font-semibold">Energy</h3>
      {expertMode ? <button type="button" role="switch" aria-label="Energy" aria-checked={source !== 'off'}
        disabled={!!reason || busy} title={reason} onClick={() => { cancelStep(); void patch({ energy_source: source === 'off' ? lastSources[profile!.id] ?? 'sustained' : 'off' }) }}
        className="relative h-11 w-14 shrink-0 rounded-full disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
        <span aria-hidden="true" className={`absolute left-1 top-2 h-7 w-12 rounded-full transition-colors ${source === 'off' ? 'bg-secondary' : 'bg-green-500'}`}>
          <span className={`absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-white shadow-sm transition-transform ${source === 'off' ? '' : 'translate-x-5'}`} />
        </span>
      </button> : <span className="text-xs text-muted-foreground">{source === 'off' ? 'Off' : 'On'}</span>}
    </div>
    {reason && <p className="mb-3 text-xs text-muted-foreground">{reason}</p>}
    {gauge}
    <div className="mt-2 mb-2 flex justify-between gap-3" aria-label="Energy effects">
      {(['low', 'high'] as const).map(role => {
        const effect = active ? effects.find(item => item.id === profile?.[`${role}_energy_effect_id`]) : undefined
        return <div key={role} data-testid={`${role}-energy-effect`}
          className={`min-w-0 flex-1 break-words ${role === 'high' ? 'text-right' : ''}`}>
          <span className="text-xs text-muted-foreground">{role === 'low' ? 'Low' : 'High'} · </span>
          {effect ? <a href={`#effects/${encodeURIComponent(effect.id)}`}
            onClick={e => { if (onOpenEffect) { e.preventDefault(); onOpenEffect(effect.id) } }}
            className={`text-xs hover:underline underline-offset-2 ${role === 'low' && source === 'off' ? 'text-muted-foreground' : 'text-primary'}`}>{effect.name}</a>
            : <span className="text-xs text-muted-foreground">—</span>}
        </div>
      })}
    </div>
    {readouts}
    {expertMode && <EnergySourceControls compact source={source}
      floor={draft.floor} ceiling={draft.ceiling} tau={draft.tau} onChange={change}
      peakAuto={profile?.peak_envelope_auto ?? true} attack={draft.attack} release={draft.release}
      reshapeEnabled={profile?.peak_reshape_enabled ?? false} reshapePower={draft.reshapePower}
      onCommit={() => commit()} onStep={step} disabled={!active || !profile} pending={busy} />}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </section>
}

function draftKey(field: EnergySetting) {
  return field === 'lufs_floor' ? 'floor' : field === 'lufs_ceiling' ? 'ceiling'
    : field === 'peak_reshape_power' ? 'reshapePower' : field === 'peak_attack_s' ? 'attack' : field === 'peak_release_s' ? 'release' : 'tau'
}
