import { expect, it } from 'vitest'
import { playerIcon } from '@/lib/playerIcons'

it.each([
  [{ modelname: 'YeneY', name: 'Study (Sonos)' }, 'Sonos'],
  [{ modelname: 'YeneY', sonos_room: 'Study' }, 'Sonos'],
  [{ modelname: 'YeneY', name: 'Study' }, 'Speaker'],
  [{ name: 'Study (Sonos)' }, 'Speaker'],
  [{ model: 'baby' }, 'Radio'],
  [{ modelname: 'SqueezeLite-pCP' }, 'RaspberryPi'],
  [{ firmware: '8.5.0-pCP' }, 'RaspberryPi'],
  ...['b8:27:eb', 'dc:a6:32', 'e4:5f:01', 'd8:3a:dd', '2c:cf:67'].map(prefix => [{ playerid: `${prefix.toUpperCase()}:00:11:22` }, 'RaspberryPi']),
  [{ managed: true, modelname: 'YeneY', name: 'LampaStream LMS (Sonos)' }, 'LMS'],
  [{ name: 'LampaStream LMS', modelname: 'YeneY', sonos_room: 'Study' }, 'LMS'],
  [{ type: 'AirPlay', managed: true }, 'AirPlay'],
  [{ model: 'unknown' }, 'Speaker'],
  [{}, 'Speaker'],
] as const)('maps %j to %s', (identity, expected) => {
  expect(playerIcon(identity)).toBe(expected)
})
