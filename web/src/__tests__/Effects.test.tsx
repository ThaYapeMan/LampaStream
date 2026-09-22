import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Effects, EFFECT_DEFAULTS } from '../pages/Effects'
import * as apiModule from '../lib/api'

// ── mocks ────────────────────────────────────────────────────────────────────

vi.mock('../hooks/usePreviewSocket', () => ({
  usePreviewSocket: () => ({
    colour: { r: 0, g: 0, b: 0 },
    channel_colours: [],
    onset: false,
    onset_bass: false,
    onset_mid: false,
    onset_treble: false,
    mix: 0,
    energy: 0.5,
    bars: [],
    status: null,
    connected: false,
    reconnectAttempt: 0,
  }),
}))

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    getEffects: vi.fn().mockResolvedValue([
      {
        id: 'e1', name: 'Party Fireworks', effect_type: 'fireworks',
        effect_speed: 2.5, effect_decay: 0.6, sensitivity: 1.4, brightness_floor: 0.05,
        bass_hz: 250, mid_hz: 2000, exertion_clip: 3.0, onset_flash_intensity: 0.3,
      },
      {
        id: 'e2', name: 'Calm Spectrum', effect_type: 'spectrum_rgb',
        effect_speed: 1.0, effect_decay: 0.3, sensitivity: 0.6, brightness_floor: 0.15,
        bass_hz: 250, mid_hz: 2000, exertion_clip: 3.0, onset_flash_intensity: 0.0,
      },
      {
        id: 'e3', name: 'Lights Off', effect_type: 'none',
        effect_speed: 1.0, effect_decay: 0.3, sensitivity: 1.0, brightness_floor: 0.15,
        bass_hz: 250, mid_hz: 2000, exertion_clip: 3.0, onset_flash_intensity: 0.0,
      },
    ]),
    createEffect: vi.fn().mockResolvedValue({
      id: 'new-id', name: 'New Effect', effect_type: 'spectrum_rgb',
      effect_speed: 1.0, effect_decay: 0.3, sensitivity: 1.0, brightness_floor: 0.15,
      bass_hz: 250, mid_hz: 2000, exertion_clip: 3.0, onset_flash_intensity: 0.0,
    }),
    updateEffect: vi.fn().mockResolvedValue(undefined),
    deleteEffect: vi.fn().mockResolvedValue(undefined),
    getAnalysers: vi.fn().mockResolvedValue([]),
    getCouplings: vi.fn().mockResolvedValue([]),
    getEnergyProfiles: vi.fn().mockResolvedValue([]),
  }
})

// ── helpers ──────────────────────────────────────────────────────────────────

async function renderEffects() {
  const user = userEvent.setup()
  render(<Effects />)
  await screen.findByTestId('effects-gallery')
  return user
}

async function renderEffectsInWorkspace() {
  const user = userEvent.setup()
  render(<Effects />)
  await screen.findByTestId('effects-gallery')
  await user.click(screen.getByTestId('edit-effect-e1'))
  await screen.findByTestId('editor-name-input')
  return user
}

async function renderSpectrumInWorkspace() {
  const user = userEvent.setup()
  render(<Effects />)
  await screen.findByTestId('effects-gallery')
  await user.click(screen.getByTestId('edit-effect-e2'))
  await screen.findByTestId('editor-name-input')
  return user
}

async function renderNoneInWorkspace() {
  const user = userEvent.setup()
  render(<Effects />)
  await screen.findByTestId('effects-gallery')
  await user.click(screen.getByTestId('edit-effect-e3'))
  await screen.findByTestId('editor-name-input')
  return user
}

async function renderNewEffectInWorkspace() {
  const user = userEvent.setup()
  render(<Effects />)
  await screen.findByTestId('effects-gallery')
  await user.click(screen.getByTestId('new-effect-btn'))
  await screen.findByTestId('editor-name-input')
  return user
}

// ── gallery tests ─────────────────────────────────────────────────────────────

describe('Effects gallery', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders a card for each effect', async () => {
    await renderEffects()
    expect(screen.getByTestId('effect-card-e1')).toBeDefined()
    expect(screen.getByTestId('effect-card-e2')).toBeDefined()
  })

  it('shows effect name and type label on each card', async () => {
    await renderEffects()
    const card1 = screen.getByTestId('effect-card-e1')
    expect(within(card1).getByText('Party Fireworks')).toBeDefined()
    expect(within(card1).getByText('Fireworks')).toBeDefined()

    const card2 = screen.getByTestId('effect-card-e2')
    expect(within(card2).getByText('Calm Spectrum')).toBeDefined()
    expect(within(card2).getByText('Spectrum RGB')).toBeDefined()
  })

  it('shows human-readable summary instead of raw numbers', async () => {
    await renderEffects()
    const card1 = screen.getByTestId('effect-card-e1')
    // sensitivity 1.4 → "Balanced", decay 0.6 → "Punchy", speed 2.5 → nothing (below 2.5 threshold)
    expect(within(card1).getByText(/Balanced.*Punchy/)).toBeDefined()
    // Does NOT show raw numbers like "1.4" in the summary area
    const card2 = screen.getByTestId('effect-card-e2')
    expect(within(card2).getByText('Subtle')).toBeDefined()
  })

  it('renders EffectPreview dots for each card', async () => {
    await renderEffects()
    const previews = screen.getAllByTestId('effect-preview')
    expect(previews.length).toBeGreaterThanOrEqual(2)
  })

  it('opens editor when Edit is clicked', async () => {
    const user = await renderEffects()
    await user.click(screen.getByTestId('edit-effect-e1'))
    await screen.findByTestId('editor-name-input')
    expect((screen.getByTestId('editor-name-input') as HTMLInputElement).value).toBe('Party Fireworks')
  })

  it('opens new editor on New effect button', async () => {
    const user = await renderEffects()
    await user.click(screen.getByTestId('new-effect-btn'))
    await screen.findByTestId('editor-name-input')
    expect((screen.getByTestId('editor-name-input') as HTMLInputElement).value).toBe('')
  })
})

// ── workspace editor tests ────────────────────────────────────────────────────

describe('Effects workspace editor', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows name input with effect name', async () => {
    await renderEffectsInWorkspace()
    expect((screen.getByTestId('editor-name-input') as HTMLInputElement).value).toBe('Party Fireworks')
  })

  it('updates name when typed', async () => {
    const user = await renderEffectsInWorkspace()
    const input = screen.getByTestId('editor-name-input') as HTMLInputElement
    await user.clear(input)
    await user.type(input, 'Renamed')
    expect(input.value).toBe('Renamed')
  })

  it('Save button is disabled when name is empty', async () => {
    const user = await renderEffectsInWorkspace()
    const input = screen.getByTestId('editor-name-input') as HTMLInputElement
    await user.clear(input)
    const saveBtn = screen.getByTestId('editor-save')
    expect(saveBtn).toBeDisabled()
  })

  it('Cancel returns to gallery', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByText('Cancel'))
    await screen.findByTestId('effects-gallery')
  })

  it('shows effect type selector with current type', async () => {
    await renderEffectsInWorkspace()
    const display = screen.getByTestId('effect-type-display')
    expect(within(display).getByText('Fireworks')).toBeDefined()
  })

  it('effect type picker opens and allows selection', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('effect-type-change'))
    const picker = await screen.findByTestId('effect-type-picker')
    expect(picker).toBeDefined()
    expect(screen.getByTestId('type-option-spectrum_rgb')).toBeDefined()
    expect(screen.getByTestId('type-option-fireworks')).toBeDefined()
    await user.click(screen.getByTestId('type-option-spectrum_rgb'))
    const display = await screen.findByTestId('effect-type-display')
    expect(within(display).getByText('Spectrum RGB')).toBeDefined()
  })

  it('shows the large effect preview', async () => {
    await renderEffectsInWorkspace()
    const previews = screen.getAllByTestId('effect-preview')
    expect(previews.length).toBeGreaterThan(0)
  })

  it('preview input buttons are present', async () => {
    await renderEffectsInWorkspace()
    expect(screen.getByTestId('preview-calm')).toBeDefined()
    expect(screen.getByTestId('preview-groove')).toBeDefined()
    expect(screen.getByTestId('preview-beat-heavy')).toBeDefined()
    expect(screen.getByTestId('preview-live')).toBeDefined()
  })

  it('preview input switching changes active button', async () => {
    const user = await renderEffectsInWorkspace()
    const calmBtn = screen.getByTestId('preview-calm')
    await user.click(calmBtn)
    expect(calmBtn.className).toMatch(/bg-primary/)
  })

  it('Live preview button is disabled when not connected', async () => {
    await renderEffectsInWorkspace()
    const liveBtn = screen.getByTestId('preview-live') as HTMLButtonElement
    expect(liveBtn.disabled).toBe(true)
  })
})

// ── Standard / Expert mode ────────────────────────────────────────────────────

describe('Standard / Expert mode', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('Standard mode is active by default', async () => {
    await renderEffectsInWorkspace()
    const standardBtn = screen.getByTestId('mode-standard-btn')
    expect(standardBtn.className).toMatch(/font-semibold/)
    expect(screen.queryByTestId('field-bass-hz')).toBeNull()
    expect(screen.queryByTestId('field-exertion-clip')).toBeNull()
  })

  it('Expert mode button exists in header', async () => {
    await renderEffectsInWorkspace()
    expect(screen.getByTestId('mode-expert-btn')).toBeDefined()
  })

  it('switching to Expert reveals advanced fields', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    expect(screen.getByTestId('field-bass-hz')).toBeDefined()
    expect(screen.getByTestId('field-mid-hz')).toBeDefined()
    expect(screen.getByTestId('field-exertion-clip')).toBeDefined()
  })

  it('Expert mode shows exact numeric inputs for all Standard sliders', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    expect(screen.getByTestId('field-sensitivity-exact')).toBeDefined()
    expect(screen.getByTestId('field-speed-exact')).toBeDefined()       // fireworks hasSpeed
    expect(screen.getByTestId('field-decay-exact')).toBeDefined()       // fireworks hasDecay
    expect(screen.getByTestId('field-brightness-floor-exact')).toBeDefined()
    expect(screen.getByTestId('field-beat-flash-exact')).toBeDefined()
  })

  it('switching back to Standard hides Expert-only inputs', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    expect(screen.getByTestId('field-bass-hz')).toBeDefined()
    await user.click(screen.getByTestId('mode-standard-btn'))
    expect(screen.queryByTestId('field-bass-hz')).toBeNull()
    expect(screen.queryByTestId('field-sensitivity-exact')).toBeNull()
  })

  it('mode switch does not mutate draft values', async () => {
    const user = await renderEffectsInWorkspace() // e1 sensitivity=1.4
    await user.click(screen.getByTestId('mode-expert-btn'))
    const exactInput = screen.getByTestId('field-sensitivity-exact') as HTMLInputElement
    expect(exactInput.value).toBe('1.4')
    // Change to 1.8 in Expert
    await user.clear(exactInput)
    await user.type(exactInput, '1.8')
    // Switch to Standard and back
    await user.click(screen.getByTestId('mode-standard-btn'))
    await user.click(screen.getByTestId('mode-expert-btn'))
    // Value must still be 1.8
    const exactAfter = screen.getByTestId('field-sensitivity-exact') as HTMLInputElement
    expect(exactAfter.value).toBe('1.8')
  })

  it('Expert values survive Standard-mode Save', async () => {
    const user = await renderEffectsInWorkspace() // e1 bass_hz=250
    await user.click(screen.getByTestId('mode-expert-btn'))
    const bassInput = screen.getByTestId('field-bass-hz') as HTMLInputElement
    await user.clear(bassInput)
    await user.type(bassInput, '300')
    // Switch to Standard — field-bass-hz disappears
    await user.click(screen.getByTestId('mode-standard-btn'))
    expect(screen.queryByTestId('field-bass-hz')).toBeNull()
    // Save in Standard mode
    await user.click(screen.getByTestId('editor-save'))
    expect(vi.mocked(apiModule.updateEffect)).toHaveBeenCalledWith(
      'e1',
      expect.objectContaining({ bass_hz: 300 }),
    )
  })

  it('opening a new editor always starts in Standard mode', async () => {
    const user = await renderEffectsInWorkspace() // e1 editor
    await user.click(screen.getByTestId('mode-expert-btn'))
    await user.click(screen.getByText('Cancel'))
    // Open second editor
    await user.click(screen.getByTestId('edit-effect-e2'))
    await screen.findByTestId('editor-name-input')
    // Must be back in Standard
    expect(screen.queryByTestId('field-bass-hz')).toBeNull()
    expect(screen.getByTestId('mode-standard-btn').className).toMatch(/font-semibold/)
  })
})

// ── Conditional fields — applicability ───────────────────────────────────────

describe('Conditional fields — applicability', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('fireworks shows Speed and Decay fields (hasSpeed=true, hasDecay=true)', async () => {
    await renderEffectsInWorkspace() // e1 fireworks
    expect(screen.getByTestId('reset-speed')).toBeDefined()
    expect(screen.getByTestId('reset-decay')).toBeDefined()
  })

  it('spectrum_rgb does not show Speed or Decay fields (hasSpeed=false, hasDecay=false)', async () => {
    await renderSpectrumInWorkspace() // e2 spectrum_rgb
    expect(screen.queryByTestId('reset-speed')).toBeNull()
    expect(screen.queryByTestId('reset-decay')).toBeNull()
  })

  it('none type shows none-message, not behaviour section', async () => {
    await renderNoneInWorkspace() // e3 none
    expect(screen.getByTestId('section-none-message')).toBeDefined()
    expect(screen.queryByTestId('section-behaviour')).toBeNull()
  })

  it('none type does not expose Behaviour sliders in Expert mode', async () => {
    const user = await renderNoneInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    expect(screen.queryByTestId('field-sensitivity-exact')).toBeNull()
    expect(screen.queryByTestId('field-bass-hz')).toBeNull()
  })

  it('Sensitivity and Brightness floor always appear for non-none types', async () => {
    await renderSpectrumInWorkspace() // spectrum_rgb, no speed/decay
    expect(screen.getByTestId('reset-sensitivity')).toBeDefined()
    expect(screen.getByTestId('reset-brightness-floor')).toBeDefined()
    expect(screen.getByTestId('reset-beat-flash')).toBeDefined()
  })
})

// ── Reset behavior ────────────────────────────────────────────────────────────

describe('Reset behavior', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('sensitivity Reset is disabled (aria-disabled=true) at default value', async () => {
    await renderNewEffectInWorkspace() // all defaults
    const resetBtn = screen.getByTestId('reset-sensitivity')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('true')
  })

  it('sensitivity Reset is active (aria-disabled=false) when non-default', async () => {
    await renderEffectsInWorkspace() // e1 sensitivity=1.4
    const resetBtn = screen.getByTestId('reset-sensitivity')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('false')
  })

  it('clicking sensitivity Reset restores model default', async () => {
    const user = await renderEffectsInWorkspace() // e1 sensitivity=1.4
    await user.click(screen.getByTestId('mode-expert-btn'))
    const exact = screen.getByTestId('field-sensitivity-exact') as HTMLInputElement
    expect(exact.value).toBe('1.4')
    await user.click(screen.getByTestId('reset-sensitivity'))
    expect(exact.value).toBe(String(EFFECT_DEFAULTS.sensitivity))
  })

  it('resetting sensitivity does not change decay', async () => {
    const user = await renderEffectsInWorkspace() // e1 decay=0.6
    await user.click(screen.getByTestId('mode-expert-btn'))
    const decayInput = screen.getByTestId('field-decay-exact') as HTMLInputElement
    expect(decayInput.value).toBe('0.6')
    await user.click(screen.getByTestId('reset-sensitivity'))
    expect(decayInput.value).toBe('0.6')
  })

  it('brightness floor Reset is disabled when at default (e2: 0.15)', async () => {
    await renderSpectrumInWorkspace() // e2 brightness_floor=0.15 (default)
    const resetBtn = screen.getByTestId('reset-brightness-floor')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('true')
  })

  it('brightness floor Reset is active when non-default (e1: 0.05)', async () => {
    await renderEffectsInWorkspace() // e1 brightness_floor=0.05
    const resetBtn = screen.getByTestId('reset-brightness-floor')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('false')
  })

  it('clicking brightness floor Reset restores 0.15', async () => {
    const user = await renderEffectsInWorkspace() // e1 brightness_floor=0.05
    await user.click(screen.getByTestId('mode-expert-btn'))
    const exact = screen.getByTestId('field-brightness-floor-exact') as HTMLInputElement
    expect(exact.value).toBe('0.05')
    await user.click(screen.getByTestId('reset-brightness-floor'))
    expect(exact.value).toBe(String(EFFECT_DEFAULTS.brightness_floor))
  })

  it('beat flash Reset is disabled at default (0.0)', async () => {
    await renderNewEffectInWorkspace() // all defaults — onset_flash_intensity=0.0
    const resetBtn = screen.getByTestId('reset-beat-flash')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('true')
  })

  it('beat flash Reset is active when non-default (e1: 0.3)', async () => {
    await renderEffectsInWorkspace() // e1 onset_flash_intensity=0.3
    const resetBtn = screen.getByTestId('reset-beat-flash')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('false')
  })

  it('freq-bands Reset is disabled when both at default', async () => {
    const user = await renderEffectsInWorkspace() // e1 bass=250,mid=2000 (defaults)
    await user.click(screen.getByTestId('mode-expert-btn'))
    const resetBtn = screen.getByTestId('reset-freq-bands')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('true')
  })

  it('freq-bands Reset becomes active after changing bass_hz', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    const bassInput = screen.getByTestId('field-bass-hz') as HTMLInputElement
    await user.clear(bassInput)
    await user.type(bassInput, '400')
    const resetBtn = screen.getByTestId('reset-freq-bands')
    expect(resetBtn.getAttribute('aria-disabled')).toBe('false')
  })

  it('freq-bands Reset restores both bass and mid to defaults', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('mode-expert-btn'))
    const bassInput = screen.getByTestId('field-bass-hz') as HTMLInputElement
    const midInput  = screen.getByTestId('field-mid-hz')  as HTMLInputElement
    await user.clear(bassInput)
    await user.type(bassInput, '400')
    await user.click(screen.getByTestId('reset-freq-bands'))
    expect(bassInput.value).toBe(String(EFFECT_DEFAULTS.bass_hz))
    expect(midInput.value).toBe(String(EFFECT_DEFAULTS.mid_hz))
  })
})

// ── Preview Input — mutation safety ──────────────────────────────────────────

describe('Preview Input — mutation safety', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('switching preview input does not call updateEffect', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('preview-calm'))
    await user.click(screen.getByTestId('preview-beat-heavy'))
    await user.click(screen.getByTestId('preview-groove'))
    expect(vi.mocked(apiModule.updateEffect)).not.toHaveBeenCalled()
  })

  it('preview-calm activates Calm button', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('preview-calm'))
    expect(screen.getByTestId('preview-calm').className).toMatch(/bg-primary/)
    expect(screen.getByTestId('preview-groove').className).not.toMatch(/bg-primary/)
  })

  it('preview-beat-heavy activates Beat-heavy button', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('preview-beat-heavy'))
    expect(screen.getByTestId('preview-beat-heavy').className).toMatch(/bg-primary/)
  })

  it('switching preview input does not dirty the form (name-based save guard unaffected)', async () => {
    const user = await renderNewEffectInWorkspace()
    // New editor: name is empty, save is disabled
    expect(screen.getByTestId('editor-save')).toBeDisabled()
    // Switch preview inputs
    await user.click(screen.getByTestId('preview-calm'))
    await user.click(screen.getByTestId('preview-beat-heavy'))
    // Save still disabled — no name entered
    expect(screen.getByTestId('editor-save')).toBeDisabled()
  })

  it('preview input state resets to groove when opening a different editor', async () => {
    const user = await renderEffectsInWorkspace()
    await user.click(screen.getByTestId('preview-calm'))
    expect(screen.getByTestId('preview-calm').className).toMatch(/bg-primary/)
    // Cancel and open e2
    await user.click(screen.getByText('Cancel'))
    await user.click(screen.getByTestId('edit-effect-e2'))
    await screen.findByTestId('editor-name-input')
    // groove should be the default active button
    expect(screen.getByTestId('preview-groove').className).toMatch(/bg-primary/)
  })
})

// ── EffectPreview unit tests ──────────────────────────────────────────────────

describe('EffectPreview dots', () => {
  it('renders the correct number of dots', async () => {
    const { EffectPreview } = await import('../components/EffectPreview')
    render(<EffectPreview effectType="spectrum_rgb" count={6} />)
    const preview = screen.getByTestId('effect-preview')
    expect(preview.children.length).toBe(6)
  })

  it('renders default 8 dots', async () => {
    const { EffectPreview } = await import('../components/EffectPreview')
    render(<EffectPreview effectType="mono_pulse" />)
    const preview = screen.getByTestId('effect-preview')
    expect(preview.children.length).toBe(8)
  })

  it('renders for none effect type without crash', async () => {
    const { EffectPreview } = await import('../components/EffectPreview')
    render(<EffectPreview effectType="none" />)
    expect(screen.getByTestId('effect-preview')).toBeDefined()
  })

  it('band_colours shows each chosen colour directly, not an averaged blend', async () => {
    const { EffectPreview } = await import('../components/EffectPreview')
    const bandColours = ['#F42525', '#25F425', '#2525F4']
    render(<EffectPreview effectType="band_colours" bandColours={bandColours} count={3} />)
    const dots = screen.getByTestId('effect-preview').children
    // Each slot retains its band's hue instead of sharing a flat grey average.
    expect((dots[0] as HTMLElement).style.backgroundColor).not.toBe((dots[1] as HTMLElement).style.backgroundColor)
    expect((dots[1] as HTMLElement).style.backgroundColor).not.toBe((dots[2] as HTMLElement).style.backgroundColor)
  })

  it('band_colours pads unused dot slots grey, symmetrically, when there are fewer bands than slots', async () => {
    const { EffectPreview } = await import('../components/EffectPreview')
    const bandColours = ['#F42525', '#F4F425', '#25F425', '#25F4F4', '#2525F4', '#F425F4']
    render(<EffectPreview effectType="band_colours" bandColours={bandColours} count={8} />)
    const dots = screen.getByTestId('effect-preview').children
    expect(dots.length).toBe(8)
    const grey = 'rgb(91, 97, 112)' // emissiveRgb(SLATE, intensity=0.35) — a clearly visible dim slate grey, not near-black
    expect((dots[0] as HTMLElement).style.backgroundColor).toBe(grey)
    expect((dots[7] as HTMLElement).style.backgroundColor).toBe(grey)
    // The six real bands occupy the central slots, in palette order.
    for (let i = 1; i <= 6; i++) {
      expect((dots[i] as HTMLElement).style.backgroundColor).not.toBe(grey)
    }
  })
})


describe('Gradient palette', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows four palette choices in Standard mode only for gradient and saves the selection', async () => {
    const user = await renderSpectrumInWorkspace()
    expect(screen.queryByTestId('field-gradient-palette')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('effect-type-change'))
    await user.click(screen.getByTestId('type-option-gradient'))
    const palette = screen.getByTestId('field-gradient-palette')
    expect(palette).toHaveValue('sunset')
    expect(within(palette).getAllByRole('option').map(o => o.getAttribute('value')))
      .toEqual(['sunset', 'ocean', 'neon', 'monochrome'])
    const preview = screen.getAllByTestId('effect-preview').find(p => p.querySelector('.w-10'))!
    const sunset = (preview.firstElementChild as HTMLElement).style.backgroundColor
    await user.selectOptions(palette, 'ocean')
    expect((preview.firstElementChild as HTMLElement).style.backgroundColor).not.toBe(sunset)
    await user.click(screen.getByTestId('editor-save'))
    expect(apiModule.updateEffect).toHaveBeenCalledWith('e2', expect.objectContaining({
      effect_type: 'gradient', gradient_palette: 'ocean',
    }))
  })

  it('hides palette controls for every other effect type', async () => {
    const user = await renderSpectrumInWorkspace()
    for (const effect of apiModule.EFFECTS.filter(e => e.id !== 'gradient')) {
      await user.click(screen.getByTestId('effect-type-change'))
      await user.click(screen.getByTestId(`type-option-${effect.id}`))
      expect(screen.queryByTestId('field-gradient-palette')).not.toBeInTheDocument()
    }
  })
})

describe('Band Colours', () => {
  beforeEach(() => { vi.clearAllMocks() })

  async function openBands(spatial = false) {
    const user = await renderSpectrumInWorkspace()
    await user.click(screen.getByTestId('effect-type-change'))
    await user.click(screen.getByTestId(`type-option-band_colours${spatial ? '_spatial' : ''}`))
    return user
  }

  it.each([false, true])('offers count, evenly spaced colours and approved presets in Standard mode (spatial=%s)', async spatial => {
    const user = await openBands(spatial)
    const panel = screen.getByRole('region', { name: 'Band colours' })
    expect(within(panel).queryByRole('region', { name: 'Colour Table & Playback' })).not.toBeInTheDocument()
    expect(within(panel).getByLabelText('Bass colour')).toHaveValue('#f42525')
    expect(within(panel).getByLabelText('Mid colour')).toHaveValue('#25f425')
    expect(within(panel).getByLabelText('Treble colour')).toHaveValue('#2525f4')
    expect(within(panel).getByText(/Default range preview/)).toBeVisible()
    expect(screen.getByRole('group', { name: 'Presets for Bass' }).querySelectorAll('button')).toHaveLength(14)
    fireEvent.change(screen.getByLabelText('Bass colour'), { target: { value: '#123456' } })
    expect(screen.getByLabelText('Bass colour')).toHaveValue('#123456')
    await user.click(within(screen.getByTestId('band-row-1')).getByRole('button'))
    await user.click(screen.getByRole('button', { name: 'Use #FF9E3B' }))
    expect(screen.getByLabelText('Mid colour')).toHaveValue('#ff9e3b')
    await user.click(screen.getByRole('button', { name: 'Distribute evenly' }))
    expect(screen.getByLabelText('Mid colour')).toHaveValue('#25f425')
    for (const n of [5, 8, 3]) {
      await user.click(within(screen.getByRole('group', { name: 'Band count' })).getByRole('button', { name: String(n) }))
      expect(panel.querySelectorAll('input[type="color"]')).toHaveLength(n)
    }
    await user.click(screen.getByTestId('editor-save'))
    expect(apiModule.updateEffect).toHaveBeenCalledWith('e2', expect.objectContaining({
      effect_type: spatial ? 'band_colours_spatial' : 'band_colours',
      band_colours: ['#F42525', '#25F425', '#2525F4'], band_playback: 'static', band_advance: 'beat', band_advance_interval_s: 2,
    }))
  })

  it('reorders colours without moving frequency labels and preserves Expert playback when returning to Standard', async () => {
    const user = await openBands()
    await user.click(screen.getByTestId('mode-expert-btn'))
    const panel = screen.getByRole('region', { name: 'Colour Table & Playback' })
    const range = screen.getByTestId('band-row-0').textContent?.split('#')[0]
    await user.click(within(panel).getByRole('button', { name: 'Move Mid up' }))
    expect(screen.getByLabelText('Bass colour')).toHaveValue('#25f425')
    expect(screen.getByTestId('band-row-0').textContent?.split('#')[0]).toBe(range)
    expect(screen.queryByRole('group', { name: 'Advance on' })).not.toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: 'Loop', exact: true }))
    expect(screen.getByRole('button', { name: 'Beat', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByLabelText('Interval (s)')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Every…', exact: true }))
    const interval = screen.getByLabelText('Interval (s)')
    await user.clear(interval); await user.type(interval, '4.5')
    await user.click(screen.getByTestId('mode-standard-btn'))
    expect(screen.queryByRole('region', { name: 'Colour Table & Playback' })).not.toBeInTheDocument()
    await user.click(screen.getByTestId('editor-save'))
    expect(apiModule.updateEffect).toHaveBeenCalledWith('e2', expect.objectContaining({
      band_colours: ['#25F425', '#F42525', '#2525F4'], band_playback: 'loop', band_advance: 'timer', band_advance_interval_s: 4.5,
    }))
  })

  it('opens initialEffectId once through the existing editor and stays closed after saving', async () => {
    const user = userEvent.setup()
    render(<Effects initialEffectId="e2" />)
    expect(await screen.findByTestId('editor-name-input')).toHaveValue('Calm Spectrum')
    await user.click(screen.getByTestId('editor-save'))
    expect(await screen.findByTestId('effects-gallery')).toBeVisible()
    expect(screen.queryByTestId('editor-name-input')).not.toBeInTheDocument()
  })

  it('ignores an unknown initialEffectId', async () => {
    render(<Effects initialEffectId="missing" />)
    expect(await screen.findByTestId('effects-gallery')).toBeVisible()
  })

  it('uses the matching active analyser range for read-only frequency labels', async () => {
    vi.mocked(apiModule.getCouplings).mockResolvedValueOnce([{ id: 'c', analyser_id: 'a', energy_profile_id: 'ep' }] as never)
    vi.mocked(apiModule.getEnergyProfiles).mockResolvedValueOnce([{ id: 'ep', high_energy_effect_id: 'e2' }] as never)
    vi.mocked(apiModule.getAnalysers).mockResolvedValueOnce([{ id: 'a', name: 'Room analysis', lower_cutoff_freq: 20, higher_cutoff_freq: 20000 }] as never)
    const user = userEvent.setup()
    render(<Effects initialEffectId="e2" activeCouplingId="c" />)
    await screen.findByTestId('editor-name-input')
    await user.click(screen.getByTestId('effect-type-change'))
    await user.click(screen.getByTestId('type-option-band_colours'))
    expect(screen.getByText(/Active analyser: Room analysis/)).toBeVisible()
    expect(screen.getByText('20–200 Hz')).toBeVisible()
    expect(screen.getByText('200–2000 Hz')).toBeVisible()
    expect(screen.getByText('2000–20000 Hz')).toBeVisible()
  })

  it('distributes the exact HSL colours at 3, 5 and 8 bands', async () => {
    const { distributeBandColours } = await import('../components/BandColoursEditor')
    expect(distributeBandColours(3)).toEqual(['#F42525', '#25F425', '#2525F4'])
    expect(distributeBandColours(5)).toEqual(['#F42525', '#CAF425', '#25F478', '#2578F4', '#CA25F4'])
    expect(distributeBandColours(8)).toEqual(['#F42525', '#F4C025', '#8CF425', '#25F459', '#25F4F4', '#2559F4', '#8C25F4', '#F425C0'])
  })
})
