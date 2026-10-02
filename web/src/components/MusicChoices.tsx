import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { getPalettes, setMusicOverride, type MusicStatus, type Palette, type EnergyProfile, type Coupling } from '@/lib/api'

export function MusicChoices({ music, coupling, profiles }: { music: MusicStatus; coupling?: Coupling; profiles: EnergyProfile[] }) {
  const [palettes, setPalettes] = useState<Palette[]>([])
  const [palette, setPalette] = useState(coupling?.manual_palette_id ?? '')
  const [energy, setEnergy] = useState(coupling?.manual_energy_profile_id ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => { getPalettes().then(setPalettes).catch(() => {}) }, [])
  useEffect(() => { setPalette(coupling?.manual_palette_id ?? ''); setEnergy(coupling?.manual_energy_profile_id ?? '') }, [coupling?.id, coupling?.manual_palette_id, coupling?.manual_energy_profile_id])
  async function choose(p: string, e: string) { setBusy(true); setError(''); try { await setMusicOverride(p, e); setPalette(p); setEnergy(e); setMessage(p || e ? 'Manual choices saved for this coupling' : 'Following genre rules') } catch (err) { setError(err instanceof Error ? err.message : 'Could not save choices') } finally { setBusy(false) } }
  return <Card data-testid="track-colours"><CardHeader><CardTitle>Track colours</CardTitle></CardHeader><CardContent className="space-y-4">
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm"><dt className="text-muted-foreground">Genre</dt><dd className="break-words">{music.genre} · {music.source}</dd><dt className="text-muted-foreground">Raw tags</dt><dd className="break-words">{music.raw_tags.join(', ') || 'Not available'}</dd></dl>
    <div className="grid gap-4 sm:grid-cols-2"><label className="space-y-2 text-sm">Palette<select aria-label="Track palette" className="min-h-11 w-full rounded-md border border-input bg-background px-3" disabled={busy} value={palette} onChange={e => choose(e.target.value, energy)}><option value="">Follow genre rule</option><option value="album-art">Album art</option>{palettes.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="space-y-2 text-sm">Energy Profile<select aria-label="Track energy profile" className="min-h-11 w-full rounded-md border border-input bg-background px-3" disabled={busy} value={energy} onChange={e => choose(palette, e.target.value)}><option value="">Follow genre rule</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div>
    {(palette || energy) && <Button variant="outline" className="min-h-11" disabled={busy} onClick={() => choose('', '')}>Clear manual choices</Button>}
    <p className="text-xs text-muted-foreground">Manual choices stay with this coupling until you clear them. {palette === 'album-art' && !music.album_art_available ? 'Waiting for artwork. The current colours are kept.' : ''}</p>
    {music.source === 'Last.fm' && <a href="https://www.last.fm" className="text-xs text-primary underline">Genre suggestions powered by Last.fm</a>}
    {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </CardContent></Card>
}
