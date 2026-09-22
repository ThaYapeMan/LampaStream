import { useState } from 'react'
import { BAND_ADVANCE_OPTIONS, BAND_PLAYBACK_OPTIONS } from '@/lib/api'
import { CompactEnergyNumber } from '@/components/EnergyBlendEditor'

// Sampled from the approved band-colours-standard.png preset swatches.
export const BAND_PRESETS = [
  '#FF3B3B', '#FF9E3B', '#FFE23B', '#C8FF3B', '#3BFF6A', '#3BFFB0', '#3BFFD6',
  '#3BA7FF', '#3B7BFF', '#7C5CFF', '#A13BFF', '#FF3BD6', '#FF3B8F', '#FFFFFF',
]

export function hslToHex(hue: number, saturation: number, lightness: number): string {
  const s = saturation / 100, l = lightness / 100
  const a = s * Math.min(l, 1 - l)
  const channel = (offset: number) => {
    const k = (offset + hue / 30) % 12
    const value = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))
    return Math.round(255 * value).toString(16).padStart(2, '0')
  }
  return `#${channel(0)}${channel(8)}${channel(4)}`.toUpperCase()
}

export const distributeBandColours = (count: number) =>
  Array.from({ length: count }, (_, i) => hslToHex(360 * i / count, 90, 55))

export function BandColoursEditor({ colours, playback, advance, interval, expertMode, lower, upper, rangeLabel,
  onColours, onPlayback, onAdvance, onInterval }: {
  colours: string[]; playback: string; advance: string; interval: string; expertMode: boolean
  lower: number; upper: number; rangeLabel: string
  onColours: (colours: string[]) => void; onPlayback: (value: string) => void
  onAdvance: (value: string) => void; onInterval: (value: string) => void
}) {
  const [selected, setSelected] = useState(0)
  const selectedBand = Math.min(selected, colours.length - 1)
  const boundary = (i: number) => Math.round(10 ** (Math.log10(Math.max(lower, 1))
    + (Math.log10(Math.max(upper, lower + 1)) - Math.log10(Math.max(lower, 1))) * i / colours.length))
  const label = (i: number) => colours.length === 3 ? ['Bass', 'Mid', 'Treble'][i] : `Band ${i + 1}`
  const apply = (i: number, colour: string) => onColours(colours.map((old, index) => index === i ? colour.toUpperCase() : old))
  const reorder = (i: number, direction: number) => {
    const next = [...colours]
    ;[next[i], next[i + direction]] = [next[i + direction], next[i]]
    onColours(next)
  }
  const buttonClass = (active: boolean) => `rounded border px-3 py-1 text-xs ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`
  return <section aria-label="Band colours" className="mt-5 space-y-4 rounded-xl border border-border p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div role="group" aria-label="Band count" className="flex items-center gap-1">
        <span className="mr-2 text-xs text-muted-foreground">Bands</span>
        {[3, 4, 5, 6, 7, 8].map(n => <button key={n} type="button" aria-pressed={colours.length === n}
          className={buttonClass(colours.length === n)} onClick={() => onColours(distributeBandColours(n))}>{n}</button>)}
      </div>
      <button type="button" className="text-xs text-primary hover:underline" onClick={() => onColours(distributeBandColours(colours.length))}>Distribute evenly</button>
    </div>
    <p className="text-xs text-muted-foreground">{rangeLabel}. Frequency ranges follow the analyser and are read-only.</p>
    <div className="space-y-1">
      {colours.map((colour, i) => <div key={i} data-testid={`band-row-${i}`} onClick={() => setSelected(i)}
        className={`flex items-center gap-3 rounded-md border p-2 ${selectedBand === i ? 'border-primary/50 bg-primary/5' : 'border-border'}`}>
        <button type="button" className="min-w-0 flex-1 text-left" aria-pressed={selectedBand === i} onClick={() => setSelected(i)}>
          <span className="block text-sm">{label(i)}</span>
          <span className="text-xs text-muted-foreground">{boundary(i)}–{boundary(i + 1)} Hz</span>
        </button>
        <input type="color" aria-label={`${label(i)} colour`} value={colour} onFocus={() => setSelected(i)}
          className="h-8 w-12 cursor-pointer rounded border border-input bg-transparent" onChange={e => apply(i, e.target.value)} />
        <span className="w-16 text-xs font-mono text-muted-foreground">{colour}</span>
      </div>)}
    </div>
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <div className="mb-2 flex justify-between text-xs text-muted-foreground">
        <span>Quick colours</span><span>Editing: {label(selectedBand)}</span>
      </div>
      <div role="group" aria-label={`Presets for ${label(selectedBand)}`} className="grid grid-cols-7 gap-2">
        {BAND_PRESETS.map(colour => <button key={colour} type="button" aria-label={`Use ${colour}`} title={colour}
          className="aspect-square max-h-20 rounded border border-white/20" style={{ backgroundColor: colour }} onClick={() => apply(selectedBand, colour)} />)}
      </div>
    </div>
    {expertMode && <section aria-label="Colour Table & Playback" className="space-y-3 border-t border-border pt-4">
      <h3 className="text-sm font-medium">Colour Table &amp; Playback</h3>
      <div className="space-y-1">
        {colours.map((colour, i) => <div key={i} className="flex items-center gap-2 text-xs">
          <span className="h-4 w-4 rounded" style={{ backgroundColor: colour }} />
          <span className="flex-1">{label(i)} · {colour}</span>
          <button type="button" aria-label={`Move ${label(i)} up`} disabled={i === 0} className="disabled:opacity-30" onClick={() => reorder(i, -1)}>▲</button>
          <button type="button" aria-label={`Move ${label(i)} down`} disabled={i === colours.length - 1} className="disabled:opacity-30" onClick={() => reorder(i, 1)}>▼</button>
        </div>)}
      </div>
      <div role="group" aria-label="Playback mode" className="flex flex-wrap gap-1">
        {BAND_PLAYBACK_OPTIONS.map(opt => <button key={opt.value} type="button" aria-pressed={playback === opt.value}
          className={buttonClass(playback === opt.value)} title={opt.description} onClick={() => onPlayback(opt.value)}>{opt.label}</button>)}
      </div>
      <p className="text-xs text-muted-foreground">{BAND_PLAYBACK_OPTIONS.find(opt => opt.value === playback)?.description}</p>
      {playback !== 'static' && <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Advance on" className="flex items-center gap-1">
          <span className="mr-2 text-xs text-muted-foreground">Advance on</span>
          {BAND_ADVANCE_OPTIONS.map(opt => <button key={opt.value} type="button" aria-pressed={advance === opt.value}
            className={buttonClass(advance === opt.value)} title={opt.description} onClick={() => onAdvance(opt.value)}>{opt.label}</button>)}
        </div>
        {advance === 'timer' && <CompactEnergyNumber label="Interval (s)" unit="" value={interval} step={0.1}
          disabled={false} invalid={!Number.isFinite(Number(interval)) || Number(interval) <= 0}
          onChange={onInterval} onStep={onInterval} />}
      </div>}
    </section>}
  </section>
}
