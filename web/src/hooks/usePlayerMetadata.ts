import { useEffect, useState } from 'react'
import { getVirtualPlayers, listLmsPlayers, type LmsPlayer } from '@/lib/api'

// Discovery is read-only and scoped to configured servers; a failed server leaves generic icons.
export function usePlayerMetadata(enabled = true) {
  const [players, setPlayers] = useState<LmsPlayer[]>([])
  useEffect(() => {
    if (!enabled) return
    let mounted = true
    async function discover() {
      try {
        const managed = await getVirtualPlayers()
        const hosts = [...new Set(managed.filter(p => p.type === 'LMS' && p.lms_host).map(p => p.lms_host))]
        const results = await Promise.all(hosts.map(host => listLmsPlayers(host).catch(() => [])))
        if (mounted) setPlayers(results.flat())
      } catch { /* Discovery is optional for decorative icons. */ }
    }
    void discover()
    return () => { mounted = false }
  }, [enabled])
  return players
}
