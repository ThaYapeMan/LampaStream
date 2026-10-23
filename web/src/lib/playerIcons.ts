export interface PlayerIdentity {
  type?: string
  managed?: boolean
  name?: string
  playerid?: string
  model?: string
  modelname?: string
  firmware?: string
  sonos_room?: string
}

// Managed receivers take precedence over external LMS model detection.
export function playerIcon(player: PlayerIdentity = {}) {
  if (player.type === 'AirPlay') return 'AirPlay'
  if (player.managed || /^lampastream lms$/i.test(player.name || '')) return 'LMS'
  if (player.modelname?.toLowerCase() === 'yeney' &&
      (/\(sonos\)\s*$/i.test(player.name || '') || player.sonos_room)) return 'Sonos'
  if (player.model?.toLowerCase() === 'baby') return 'Radio'
  if (player.modelname?.toLowerCase() === 'squeezelite-pcp' ||
      /-pcp$/i.test(player.firmware || '') ||
      /^(b8:27:eb|dc:a6:32|e4:5f:01|d8:3a:dd|2c:cf:67):/i.test(player.playerid || '')) return 'RaspberryPi'
  return 'Speaker'
}
