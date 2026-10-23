import lyrion from '@/assets/lyrion-icon.svg'

export function LyrionIcon({ size = 17 }: { size?: number }) {
  return <span aria-hidden="true" data-lyrion-icon style={{
    display: 'inline-block', width: size, height: size, backgroundColor: 'currentColor',
    maskImage: `url("${lyrion}")`, WebkitMaskImage: `url("${lyrion}")`, maskMode: 'alpha',
    maskSize: 'contain', maskRepeat: 'no-repeat', maskPosition: 'center',
    WebkitMaskSize: 'contain', WebkitMaskRepeat: 'no-repeat', WebkitMaskPosition: 'center'
  }} />
}
