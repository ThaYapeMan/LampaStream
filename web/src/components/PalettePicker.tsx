import { useEffect, useState } from 'react'
import { getPalettes, type Palette } from '@/lib/api'

export function PalettePicker({ value, rotation, onChange, onRotation }: { value: string; rotation: number; onChange: (value: string, palette?: Palette) => void; onRotation: (value: number) => void }) {
  const [palettes, setPalettes] = useState<Palette[]>([])
  useEffect(() => { getPalettes().then(setPalettes).catch(() => {}) }, [])
  return <div className="space-y-3 rounded-lg border p-4">
    <label className="block space-y-2 text-sm">Shared palette<select aria-label="Shared palette" className="min-h-11 w-full rounded-md border border-input bg-background px-3" value={value} onChange={e => onChange(e.target.value, palettes.find(p => p.id === e.target.value))}><option value="">Use existing colours</option><option value="album-art">Album art</option>{palettes.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <label className="block space-y-2 text-sm">Rotation (cycles per second)<input aria-label="Palette rotation" className="min-h-11 w-full rounded-md border border-input bg-background px-3" type="number" min={-2} max={2} step={.01} value={rotation} onChange={e => onRotation(Number(e.target.value))} /></label>
    {palettes.find(p => p.id === value) && <div className="h-8 rounded-lg" aria-label="Selected palette colours" style={{ background: `linear-gradient(90deg,${palettes.find(p => p.id === value)!.stops.map(s => `${s.colour} ${s.position}%`).join(',')})` }} />}
    <a href="/palettes" className="inline-flex min-h-11 items-center text-sm text-primary underline">Edit palettes</a>
  </div>
}
