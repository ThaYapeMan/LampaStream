export function SegmentedControl({ label, value, options, disabled = false, pending = false, onChange, fit = false }: {
  label: string; value: string; options: { value: string; label: string }[]
  disabled?: boolean; pending?: boolean; onChange: (value: string) => void; fit?: boolean
}) {
  return <div role="radiogroup" aria-label={label}
    className={fit ? 'inline-flex rounded-lg border border-border bg-background/40 p-0.5' : 'grid w-full grid-cols-2 sm:grid-cols-4 rounded-lg border border-border bg-background/40 p-0.5'}>
    {options.map((option, index) => <button key={option.value} type="button" role="radio"
      aria-checked={value === option.value} tabIndex={value === option.value || (value === 'off' && index === 0) ? 0 : -1}
      disabled={disabled} aria-disabled={disabled || pending}
      onClick={() => { if (!pending) onChange(option.value) }}
      onKeyDown={event => {
        if (pending || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const count = options.length
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1
          : (index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? count - 1 : 1)) % count
        ;(event.currentTarget.parentElement!.children[next] as HTMLButtonElement).focus()
        onChange(options[next].value)
      }}
      className={`min-h-11 sm:min-h-9 rounded-md ${fit ? 'px-3' : 'px-1'} py-2 text-xs disabled:opacity-50 ${value === option.value && option.value === 'off' ? 'bg-muted text-muted-foreground font-medium shadow-sm ring-[0.5px] ring-border' : value === option.value ? 'bg-secondary text-foreground font-medium shadow-sm ring-[0.5px] ring-border' : 'text-muted-foreground'}`}>
      <div>{option.label}</div>
    </button>)}
  </div>
}
