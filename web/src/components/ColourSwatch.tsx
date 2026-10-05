import { toDisplayRgb } from '@/lib/colorUtils'

export function ColourSwatch({ r, g, b }: { r: number; g: number; b: number }) {
  const [cr, cg, cb] = toDisplayRgb(r, g, b)
  return <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
    <span data-testid="colour-preview-size" aria-label="Channel 1 colour" className="h-4 w-4 shrink-0 rounded"
      style={{ backgroundColor: `rgb(${cr}, ${cg}, ${cb})` }} />Channel 1
  </span>
}
