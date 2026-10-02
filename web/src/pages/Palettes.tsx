import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { FloorplanPreview } from '@/components/FloorplanPreview'
import { getPalettes, savePalette, deletePalette, duplicatePalette, previewPalette, getZoneChannels, type Palette, type ChannelPosition } from '@/lib/api'

const fresh = (): Palette => ({ id: '', name: 'New palette', stops: [{ colour: '#ef553b', position: 0 }, { colour: '#ffd16b', position: 100 }] })
const css = (c: { r: number; g: number; b: number }) => `rgb(${c.r * 255},${c.g * 255},${c.b * 255})`
export function Palettes({ zoneId }: { zoneId?: string | null }) {
  const [palettes, setPalettes] = useState<Palette[]>([])
  const [draft, setDraft] = useState<Palette>(fresh)
  const [channels, setChannels] = useState<ChannelPosition[]>([])
  const [colours, setColours] = useState<Array<{ r: number; g: number; b: number }>>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const report = (e: unknown) => setError(e instanceof Error ? e.message : 'Could not save palette')
  useEffect(() => { getPalettes().then(items => { setPalettes(items); if (items[0]) setDraft(items[0]) }).catch(report) }, [])
  useEffect(() => { setChannels([]); if (zoneId) getZoneChannels(zoneId).then(setChannels).catch(report) }, [zoneId])
  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      previewPalette(draft, [...Array.from({ length: 64 }, (_, i) => i / 63), ...channels.map(c => (c.x + 1) / 2)])
        .then(items => { if (!cancelled) setColours(items) }).catch(() => { /* Save reports invalid stops; keep the last preview. */ })
    }, 200)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [draft, channels])
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await fn() } catch (e) { report(e) } finally { setBusy(false) } }
  function addStop() {
    const gaps = draft.stops.slice(1).map((s, i) => ({ i, width: s.position - draft.stops[i].position }))
    const gap = gaps.sort((a, b) => b.width - a.width)[0]
    const stops = [...draft.stops]
    stops.splice(gap.i + 1, 0, { colour: draft.stops[gap.i].colour, position: draft.stops[gap.i].position + gap.width / 2 })
    setDraft({ ...draft, stops })
  }
  return <section className="space-y-6 min-w-0">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold">Palettes</h1><p className="text-sm text-muted-foreground">Colours that belong together.</p></div><Button className="min-h-11" onClick={() => { setDraft(fresh()); setError(''); setMessage('') }}>Create palette</Button></header>
    <div className="grid gap-5 md:grid-cols-[300px_minmax(0,1fr)]">
      <Card className="min-w-0"><CardHeader><CardTitle>Your palettes</CardTitle></CardHeader><CardContent><ul className="space-y-1">{palettes.map(p => <li key={p.id}><button aria-pressed={p.id === draft.id} className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left ${p.id === draft.id ? 'bg-secondary' : 'hover:bg-secondary/50'}`} onClick={() => { setDraft(p); setError(''); setMessage('') }}><span aria-hidden="true" className="h-6 w-12 shrink-0 rounded" style={{ background: `linear-gradient(90deg,${p.stops.map(s => `${s.colour} ${s.position}%`).join(',')})` }} /><span className="break-words">{p.name}</span></button></li>)}</ul></CardContent></Card>
      <div className="space-y-5 min-w-0"><Card><CardHeader><CardTitle>{draft.id ? 'Edit palette' : 'New palette'}</CardTitle></CardHeader><CardContent className="space-y-4">
        <label className="block space-y-2 text-sm">Name<Input className="min-h-11" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
        <div><h2 className="mb-3 text-sm font-medium">Colour stops</h2><ol className="space-y-3">{draft.stops.map((s, i) => <li key={i} className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
          <label className="text-xs">Colour {i + 1}<input aria-label={`Colour ${i + 1}`} type="color" className="ml-2 h-11 w-12 rounded border bg-secondary" value={s.colour} onChange={e => setDraft({ ...draft, stops: draft.stops.map((v, j) => j === i ? { ...v, colour: e.target.value } : v) })} /></label>
          <label className="flex basis-full min-w-0 flex-1 items-center gap-2 text-xs">Position<input aria-label={`Position ${i + 1}`} type="range" className="h-11 min-w-0 flex-1" min={i ? draft.stops[i - 1].position + .1 : 0} max={i < draft.stops.length - 1 ? draft.stops[i + 1].position - .1 : 100} step={.1} value={s.position} onChange={e => setDraft({ ...draft, stops: draft.stops.map((v, j) => j === i ? { ...v, position: Number(e.target.value) } : v) })} /><output className="w-12 text-right tabular-nums">{s.position.toFixed(1)}%</output></label>
          <Button variant="ghost" className="min-h-11" disabled={draft.stops.length <= 2} aria-label={`Remove stop ${i + 1}`} onClick={() => setDraft({ ...draft, stops: draft.stops.filter((_, j) => i !== j) })}>Remove</Button>
        </li>)}</ol></div>
        <Button variant="outline" className="min-h-11" disabled={draft.stops.length >= 8} onClick={addStop}>Add stop</Button>
        <div className="flex h-10 overflow-hidden rounded-lg" aria-label="Palette preview">{colours.slice(0, 64).map((c, i) => <span key={i} className="flex-1" style={{ background: css(c) }} />)}</div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
        <footer className="flex flex-wrap justify-between gap-3 border-t pt-4"><div className="flex flex-wrap gap-2">{draft.id && <><ConfirmDialog title={`Delete ${draft.name}?`} description="This removes the palette. Palettes in use must be reassigned first." trigger={<Button variant="ghost" className="min-h-11 text-destructive">Delete…</Button>} onConfirm={() => action(async () => { await deletePalette(draft.id); const items = await getPalettes(); setPalettes(items); setDraft(items[0] ?? fresh()) })} /><Button className="min-h-11" variant="outline" disabled={busy} onClick={() => action(async () => { const p = await duplicatePalette(draft.id); setPalettes([...palettes, p]); setDraft(p) })}>Duplicate</Button></>}</div><Button className="min-h-11" disabled={busy} onClick={() => action(async () => { const p = await savePalette(draft); setPalettes([...palettes.filter(item => item.id !== p.id), p]); setDraft(p); setMessage('Palette saved') })}>{busy ? 'Saving…' : 'Save palette'}</Button></footer>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Preview in your room</CardTitle></CardHeader><CardContent><div className="mx-auto max-w-sm"><FloorplanPreview channels={channels} colours={colours.slice(64)} onset={false} /></div>{!channels.length && <p className="text-sm text-muted-foreground">Activate a coupling to preview the palette on its floor plan.</p>}<p className="mt-3 text-xs text-muted-foreground">A preview only. Your lights keep playing.</p></CardContent></Card></div>
    </div>
  </section>
}
