import { describe, expect, it } from 'vitest'
import { validateEnergySettings } from '../components/EnergyBlendEditor'

const settings = { source:'peak_envelope', floor:'-30', ceiling:'-8', tau:'60', peakAuto:false, attack:'0.05', release:'2' }

describe('energy settings validation', () => {
  it('accepts ordered finite Manual values and ignores manual values in Auto', () => {
    expect(validateEnergySettings(settings)).toBeNull()
    expect(validateEnergySettings({...settings, peakAuto:true, attack:'bad', release:'0'})).toBeNull()
  })
  it.each(['', 'NaN', 'Infinity'])('rejects non-finite Manual attack %s', attack => {
    expect(validateEnergySettings({...settings, attack})).toBe('Energy source settings must be finite')
    expect(validateEnergySettings({...settings, release:attack})).toBe('Energy source settings must be finite')
  })
  it.each(['0', '-1'])('rejects non-positive Manual times %s', value => {
    expect(validateEnergySettings({...settings, attack:value})).toBe('peak_attack_s and peak_release_s must be positive')
    expect(validateEnergySettings({...settings, release:value})).toBe('peak_attack_s and peak_release_s must be positive')
  })
  it.each(['2', '3'])('rejects attack >= release: %s', attack => {
    expect(validateEnergySettings({...settings, attack})).toBe('peak_attack_s must be below peak_release_s')
  })
  it('retains the existing LUFS validation messages', () => {
    expect(validateEnergySettings({...settings, source:'loudness_fixed', floor:'-5'})).toBe('lufs_floor must be below lufs_ceiling')
    expect(validateEnergySettings({...settings, source:'loudness_adaptive', tau:'0'})).toBe('adaptation_tau_s must be positive')
  })
})

it.each([true, false])('validates reshape independently of Auto=%s', peakAuto => {
  for (const reshapePower of ['', 'NaN', 'Infinity', '0', '-1', '1.1']) {
    expect(validateEnergySettings({...settings, peakAuto, reshapeEnabled:true, reshapePower}))
      .toBe('peak_reshape_power must be finite and in (0, 1]')
    expect(validateEnergySettings({...settings, peakAuto, reshapeEnabled:false, reshapePower})).toBeNull()
  }
  expect(validateEnergySettings({...settings, peakAuto, reshapeEnabled:true, reshapePower:'0.4'})).toBeNull()
})

it.each([true, false])('still validates Manual AGC with reshape=%s', reshapeEnabled => {
  expect(validateEnergySettings({...settings, reshapeEnabled, reshapePower:'0.4', attack:'0'}))
    .toBe('peak_attack_s and peak_release_s must be positive')
  expect(validateEnergySettings({...settings, peakAuto:true, reshapeEnabled, reshapePower:'0.4', attack:'bad'})).toBeNull()
})
