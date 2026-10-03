import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { releaseLights, takeLights } from '@/lib/api'
import type { SocketStatus } from '@/hooks/usePreviewSocket'

export function LightsRow({ couplingId, output }: { couplingId: string; output: SocketStatus['output_status'] }) {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState('')
  const busy = useRef(false)
  const released = output?.state === 'released'
  const streaming = output?.state === 'streaming'
  const text = streaming ? 'Following the music' : released ? `Released · ${output.reason || 'The lights are available'}` :
    `${output?.state === 'reconnecting' ? 'Reconnecting the lights' : 'Light output unavailable'}${output?.reason ? ` · ${output.reason}` : ''}`
  async function act() {
    if (busy.current) return
    busy.current = true
    setPending(released ? 'Taking…' : 'Releasing…'); setError('')
    try { await (released ? takeLights : releaseLights)(couplingId) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not change the lights') }
    finally { busy.current = false; setPending(null) }
  }
  return <div>
    <div data-testid="lights-row" className="h-20 flex items-center gap-2 sm:gap-3 rounded-lg border bg-card px-3 sm:px-4">
      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${streaming ? 'bg-green-500' : released ? 'bg-muted-foreground' : 'bg-amber-500'}`} />
      <div className="min-w-0 flex-1" role="status"><div className="text-sm font-medium">Lights</div>
        <div className={`text-xs sm:text-sm line-clamp-2 ${streaming || released ? 'text-muted-foreground' : 'text-amber-700 dark:text-amber-400'}`}>{text}</div></div>
      <Button variant="outline" className="min-h-11 shrink-0 px-2 sm:px-4" disabled={!!pending} aria-busy={!!pending} onClick={act}>
        {pending || (released ? 'Take lights' : 'Release lights')}
      </Button>
    </div>
    {error && <p role="alert" className="mt-1 text-sm text-destructive">{error}</p>}
  </div>
}
