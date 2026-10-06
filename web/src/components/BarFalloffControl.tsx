import { useEffect, useId, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'

export function BarFalloffControl({ value, onChange, disabled, reason }: {
  value: number; onChange: (value: number) => void; disabled: boolean; reason?: string
}) {
  const id = useId()
  const [text, setText] = useState(value.toFixed(2))
  useEffect(() => setText(value.toFixed(2)), [value])
  function commit() {
    const parsed = Number.parseFloat(text)
    const next = Number.isFinite(parsed) ? Math.round(Math.max(.05, Math.min(1, parsed)) * 100) / 100 : value
    setText(next.toFixed(2)); onChange(next)
  }
  return <section className="space-y-2" data-testid="bar-falloff-response">
    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Response</h3>
    <label htmlFor={id} className="block text-sm">Bar falloff</label>
    <div className="flex min-w-0 items-center gap-3">
      <Slider className="min-h-11 flex-1 data-[disabled]:opacity-50" min={.05} max={1} step={.01} value={[value]}
        onValueChange={([next]) => onChange(next)} disabled={disabled} thumbLabel="Bar falloff"
        aria-describedby={`${id}-help`} data-testid="bar-falloff-slider" />
      <div className="relative shrink-0">
        <Input id={id} type="number" min={.05} max={1} step={.01} value={text}
          onChange={event => setText(event.target.value)} onBlur={commit}
          onKeyDown={event => { if (event.key === 'Enter') commit() }} disabled={disabled}
          className="min-h-11 w-24 pr-7 tabular-nums" aria-describedby={`${id}-help`}
          data-testid="bar-falloff-seconds" />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">s</span>
      </div>
    </div>
    <div className="flex justify-between gap-3 text-xs text-muted-foreground">
      <span>Crisp · 0.05 s</span><span>Smooth · 1.00 s</span>
    </div>
    <p id={`${id}-help`} className="text-xs text-muted-foreground">
      How quickly a bar drops after a hit. Shorter makes the lights crisper; longer makes them smoother.
      {reason && <span className="block mt-1">{reason}</span>}
    </p>
  </section>
}
