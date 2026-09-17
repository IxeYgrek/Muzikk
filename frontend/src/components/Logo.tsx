import clsx from 'clsx'

const BARS = [
  { x: 5, y: 10, height: 46 },
  { x: 17, y: 22, height: 34 },
  { x: 29, y: 34, height: 22 },
  { x: 41, y: 22, height: 34 },
  { x: 53, y: 10, height: 46 },
]

/** Monogram M: the top outline of the equalizer bars traces the letter. */
export function LogoMark({ className, animated = false }: { className?: string; animated?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" className={clsx('block', className)} role="img" aria-label="Muzikk">
      <defs>
        <linearGradient id="muzikk-logo-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#8B5CF6" />
          <stop offset="55%" stopColor="#7C3AED" />
          <stop offset="100%" stopColor="#DB2777" />
        </linearGradient>
      </defs>
      <g fill="url(#muzikk-logo-gradient)">
        {BARS.map((bar, index) => (
          <rect
            key={bar.x}
            x={bar.x}
            y={bar.y}
            width={8}
            height={bar.height}
            rx={4}
            className={animated ? 'origin-bottom animate-pulse' : undefined}
            style={animated ? { animationDelay: `${index * 120}ms` } : undefined}
          />
        ))}
      </g>
    </svg>
  )
}

export function Logo({
  className,
  showWordmark = true,
  size = 'md',
}: {
  className?: string
  showWordmark?: boolean
  size?: 'sm' | 'md' | 'lg'
}) {
  const marks = { sm: 'size-7', md: 'size-9', lg: 'size-14' }
  const words = { sm: 'text-lg', md: 'text-xl', lg: 'text-3xl' }
  return (
    <div className={clsx('flex items-center gap-2.5', className)}>
      <LogoMark className={marks[size]} />
      {showWordmark && (
        <span className={clsx('font-display font-bold tracking-tight gradient-text', words[size])}>
          Muzikk
        </span>
      )}
    </div>
  )
}
