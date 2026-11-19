import { describe, expect, it } from 'vitest'
import { providerLookupText } from '@/components/MetadataProviders'

describe('provider lookup text', () => {
  const paused_until = new Date(2026, 10, 20, 17, 15).getTime() / 1000
  it.each([
    ['ready', 'Lookup: found'],
    ['not_found', 'Lookup: this track is not known there'],
    ['ambiguous', 'Lookup: several possible matches, none chosen'],
    ['octave_ambiguous', 'Lookup: several possible matches, none chosen'],
    ['credentials_not_configured', 'Not set up: no access token'],
    ['authentication_failed', 'The website does not accept the access token'],
    ['blocked', 'Refused by the website (HTTP 403) — next try 20 Nov 17:15'],
    ['rate_limited', 'Asked too often — next try 20 Nov 17:15'],
    ['timeout', 'The website did not answer'],
    ['connect_timeout', 'The website did not answer'],
    ['read_timeout', 'The website did not answer'],
    ['write_timeout', 'The website did not answer'],
    ['pool_timeout', 'The website did not answer'],
    ['network_error', 'The website did not answer'],
    ['http_error', 'The website did not answer'],
    ['unreadable', "The website's answer could not be read"],
  ])('shows %s in plain English', (status, expected) => {
    expect(providerLookupText({ lookup: { status, requested_at: null },
      http_status: 403, paused_until })).toBe(expected)
  })
})
