import { Speaker } from 'lucide-react'
import { AirPlayReceiverIcon } from './MediaIcons'
import { playerIcon, type PlayerIdentity } from '@/lib/playerIcons'
import waveform from '@/assets/lyrion-icon.svg'
import sonos from '@/assets/SONOS.svg'
import radio from '@/assets/SqueezeRadio.svg'
import pi from '@/assets/raspberry-pi.svg'

export function PlayerGlyph({ identity, size = 17 }: { identity?: PlayerIdentity; size?: number }) {
  const kind = playerIcon(identity)
  if (kind === 'AirPlay') return <AirPlayReceiverIcon data-player-icon={kind} width={size} height={size} />
  if (kind === 'Speaker') return <Speaker data-player-icon={kind} size={size} />
  const asset = { LMS: waveform, Sonos: sonos, Radio: radio, RaspberryPi: pi }[kind]
  return <span aria-hidden="true" data-player-icon={kind} style={{
    display: 'inline-block', flexShrink: 0, width: size, height: size, backgroundColor: 'currentColor',
    maskImage: `url("${asset}")`, WebkitMaskImage: `url("${asset}")`, maskMode: 'alpha',
    maskSize: 'contain', maskRepeat: 'no-repeat', maskPosition: 'center',
    WebkitMaskSize: 'contain', WebkitMaskRepeat: 'no-repeat', WebkitMaskPosition: 'center'
  }} />
}
