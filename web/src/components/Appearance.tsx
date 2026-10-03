import { useEffect, useState } from 'react'

type Appearance = 'system' | 'light' | 'dark'
const key = 'lampastream.appearance'
function stored(): Appearance {
  try { const value = localStorage.getItem(key); return value === 'light' || value === 'dark' ? value : 'system' }
  catch { return 'system' }
}
export function Appearance() {
  const [choice, setChoice] = useState<Appearance>(stored)
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const theme = choice === 'system' ? (media.matches ? 'dark' : 'light') : choice
      document.documentElement.dataset.theme = theme
      document.documentElement.classList.toggle('dark', theme === 'dark')
    }
    apply(); media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [choice])
  function select(value: Appearance) {
    try { localStorage.setItem(key, value); setChoice(value) }
    catch { setChoice('system') }
  }
  return <div className="px-1 sm:px-3 pb-3">
    <div className="mb-2 px-1 text-xs text-muted-foreground">Appearance</div>
    <div role="group" aria-label="Appearance" className="flex rounded-md border bg-muted p-0.5">
      {(['system', 'light', 'dark'] as const).map(value => <button key={value} aria-pressed={choice === value}
        onClick={() => select(value)} className={`min-h-11 min-w-0 flex-1 rounded px-0.5 text-[10px] sm:text-xs ${choice === value ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'}`}>
        {value[0].toUpperCase() + value.slice(1)}
      </button>)}
    </div>
  </div>
}
