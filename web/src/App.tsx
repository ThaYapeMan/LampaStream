import { Appearance } from '@/components/Appearance'
import { useEffect, useState, lazy, Suspense } from 'react'
import { usePreviewSocket } from '@/hooks/usePreviewSocket'
import { NowPlaying } from '@/pages/NowPlaying'
import { Backup } from '@/pages/Backup'
import { Players } from '@/pages/Players'
import { Analysers } from '@/pages/Analysers'
import { Effects } from '@/pages/Effects'
import { EnergyProfiles } from '@/pages/EnergyProfiles'
import { Zones } from '@/pages/Zones'
import { Couplings } from '@/pages/Couplings'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const Palettes = lazy(() => import('@/pages/Palettes').then(m => ({ default: m.Palettes })))
const MusicSettings = lazy(() => import('@/pages/MusicSettings').then(m => ({ default: m.MusicSettings })))

type Tab = 'now-playing' | 'players' | 'analysers' | 'effects' | 'energy-profiles' | 'zones' | 'couplings' | 'backup' | 'palettes' | 'music-settings'

const NAV_ITEMS: { value: Tab; label: string }[] = [
  { value: 'now-playing',     label: 'Now Playing' },
  { value: 'couplings',       label: 'Couplings' },
  { value: 'analysers',       label: 'Analysers' },
  { value: 'palettes', label: 'Palettes' },
  { value: 'music-settings', label: 'Music settings' },
  { value: 'effects',         label: 'Effects' },
  { value: 'energy-profiles', label: 'Energy Profiles' },
  { value: 'zones',           label: 'Zones' },
  { value: 'players',         label: 'Players' },
  { value: 'backup',          label: 'Backup and restore' },
]

export function readRoute() {
  const url = new URL(window.location.href)
  const legacy = ['latency', 'virtual-players'].includes(url.pathname.slice(1)) || ['latency', 'virtual-players'].includes(url.hash.slice(1).split('?')[0])
  const name = legacy ? 'players' : (url.hash.slice(1).split('?')[0] || url.pathname.slice(1))
  const tab = NAV_ITEMS.find(item => item.value === name)?.value || 'now-playing'
  const hashQuery = new URLSearchParams(url.hash.split('?')[1] || '')
  const player = url.searchParams.get('player') || hashQuery.get('player')
  if (legacy) window.history.replaceState(null, '', `/players${player ? `?player=${encodeURIComponent(player)}` : ''}`)
  return { tab, player }
}

function ConnectionBadge({ connected, attempt }: { connected: boolean; attempt: number }) {
  if (connected) {
    return <Badge className="text-xs">● Live</Badge>
  }
  return (
    <Badge variant="destructive" className="text-xs">
      {attempt === 0 ? '● Connecting…' : `● Reconnecting (${attempt})…`}
    </Badge>
  )
}

export default function App() {
  const [expertMode, setExpertMode] = useState(() => {
    try { return localStorage.getItem('lampastream.expertMode') === 'true' }
    catch { return false }
  })
  function changeExpertMode(value: boolean) {
    setExpertMode(value)
    try { localStorage.setItem('lampastream.expertMode', String(value)) }
    catch { /* The preference still works for this session when storage is unavailable. */ }
  }
  const [effectId, setEffectId] = useState<string | null>(null)
  const [energyProfileId, setEnergyProfileId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>(() => readRoute().tab)
  const [selectedPlayer, setSelectedPlayer] = useState<string | null>(() => readRoute().player)
  function navigate(tab: Tab, player?: string | null) {
    window.history.pushState(null, '', `/${tab}${player ? `?player=${encodeURIComponent(player)}` : ''}`)
    setActiveTab(tab)
    setSelectedPlayer(player || null)
  }
  useEffect(() => {
    const update = () => { const route = readRoute(); setActiveTab(route.tab); setSelectedPlayer(route.player) }
    window.addEventListener('popstate', update)
    window.addEventListener('hashchange', update)
    return () => { window.removeEventListener('popstate', update); window.removeEventListener('hashchange', update) }
  }, [])
  const { colour, channel_colours, onset, onset_bass, onset_mid, onset_treble, mix, sustained_energy, last_energy_input, loudness_momentary_lufs, bars, normalised_bars, status, connected, reconnectAttempt } = usePreviewSocket()

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <header className="border-b border-border shrink-0">
        <div className="px-4 py-4 flex items-center justify-between">
          <h1 className="text-lg font-semibold tracking-tight">LampaStream</h1>
          <div className="flex items-center gap-3">
            <select aria-label="Editor mode" value={expertMode ? 'expert' : 'standard'}
              onChange={event => changeExpertMode(event.target.value === 'expert')}
              className="rounded border border-input bg-background px-2 py-1 text-xs">
              <option value="standard">Standard</option>
              <option value="expert">Expert</option>
            </select>
            <ConnectionBadge connected={connected} attempt={reconnectAttempt} />
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <nav className="w-28 sm:w-44 border-r border-border shrink-0 pt-2 flex flex-col">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.value}
              onClick={() => navigate(item.value)}
              className={cn(
                'min-h-11 w-full text-left px-2 sm:px-4 py-2.5 text-xs sm:text-sm transition-colors',
                activeTab === item.value
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
              )}
            >
              {item.label}
            </button>
          ))}
          <div className="mt-auto pt-6">
            <Appearance />
            {status?.version && <div className="px-2 sm:px-4 pb-4 text-xs text-muted-foreground">{status.version}</div>}
          </div>
        </nav>

        <main className="flex-1 overflow-hidden flex flex-col">
          {/* Effects, Energy Profiles, Couplings, and Analysers manage their own full-page layout */}
          {activeTab === 'energy-profiles' ? (
            <EnergyProfiles expertMode={expertMode} onExpertModeChange={changeExpertMode} initialProfileId={energyProfileId} activeCouplingId={status?.active_coupling_id ?? null} />
          ) : activeTab === 'effects' ? (
            <Effects initialEffectId={effectId} activeCouplingId={status?.active_coupling_id ?? null} />
          ) : activeTab === 'couplings' ? (
            <Couplings
              activeCouplingId={status?.active_coupling_id ?? null}
              onActivationChange={() => {}}
              onNavigate={(tab) => setActiveTab(tab as Tab)}
            />
          ) : activeTab === 'analysers' ? (
            <Analysers activeCouplingId={status?.active_coupling_id ?? null} />
          ) : (
            <div className="flex-1 overflow-y-auto">
              <div className={cn('mx-auto w-full min-w-0 px-3 sm:px-6 py-6', ['players', 'palettes', 'music-settings'].includes(activeTab) ? 'max-w-6xl' : activeTab === 'now-playing' ? 'max-w-5xl' : 'max-w-3xl')}>
                {activeTab === 'palettes' && <Suspense fallback={<p role="status">Loading palettes…</p>}><Palettes zoneId={status?.active_zone_id} /></Suspense>}
                {activeTab === 'music-settings' && <Suspense fallback={<p role="status">Loading settings…</p>}><MusicSettings /></Suspense>}
                {activeTab === 'now-playing' && (
                  <NowPlaying onOpenLatency={() => navigate('players', status?.timing_player_mac || status?.follow_target_mac || status?.sync_master)} onOpenEffect={id => { setEffectId(id); setActiveTab('effects') }} expertMode={expertMode} last_energy_input={last_energy_input} onOpenEnergyProfile={id => { setEnergyProfileId(id); setActiveTab('energy-profiles') }} colour={colour} channel_colours={channel_colours} onset={onset} onset_bass={onset_bass} onset_mid={onset_mid} onset_treble={onset_treble} mix={mix} sustained_energy={sustained_energy} loudness_momentary_lufs={loudness_momentary_lufs} bars={bars} normalised_bars={normalised_bars} status={status} connected={connected} />
                )}
                {activeTab === 'backup' && <Backup />}
                {activeTab === 'players' && <Players activeCouplingId={status?.active_coupling_id ?? null} status={status} selectedPlayer={selectedPlayer} onSelect={id => navigate('players', id)} onNowPlaying={() => navigate('now-playing')} />}
                {activeTab === 'zones' && <Zones activeCouplingId={status?.active_coupling_id ?? null} />}

              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
