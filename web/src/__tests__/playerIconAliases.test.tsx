import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { LightTiming } from '@/components/LightTiming'
import { usePlayerMetadata } from '@/hooks/usePlayerMetadata'
import type { SocketStatus } from '@/hooks/usePreviewSocket'

vi.mock('@/hooks/usePlayerMetadata', () => ({ usePlayerMetadata: vi.fn() }))
afterEach(cleanup)

it.each(['Study (Sonos)', 'Study', 'MBR', 'Sonos Port'])('keeps the Sonos timing diagram icon for %s with a saved alias', name => {
  vi.mocked(usePlayerMetadata).mockReturnValue([{ playerid: 'AA', name, modelname: 'YeneY' }])
  const status = {
    follow_target_mac: 'aa', follow_target_name: name, timing_player_name: 'Favourite room', applied_delay_ms: 1000,
    light_timing: { player_mac: 'aa', name: 'Favourite room', strategy: 'auto', trim_ms: 0,
      status: { state: 'stable', sample_count: 7, precision_ms: 10, samples: [] } },
  } as unknown as SocketStatus
  const view = render(<LightTiming status={status} />)
  const diagram = view.getByTestId('timing-diagram')
  expect(diagram).toHaveTextContent('Favourite room')
  expect(diagram.querySelector('[data-player-icon="Sonos"]')).toHaveStyle({ width: '32px', height: '32px' })
})
