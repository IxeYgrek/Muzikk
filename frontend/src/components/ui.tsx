import clsx from 'clsx'
import { Loader2, X } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import { useEffect } from 'react'

/* ------------------------------------------------------------------ button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({
  variant = 'secondary',
  size,
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ComponentProps<'button'> & {
  variant?: ButtonVariant
  size?: 'sm'
  loading?: boolean
}) {
  return (
    <button
      className={clsx('btn', `btn-${variant}`, size === 'sm' && 'btn-sm', className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------ inputs */

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <label className={clsx('block', className)}>
      {label && <span className="label">{label}</span>}
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-accent-300">{error}</span>
      ) : hint ? (
        <span className="hint mt-1 block">{hint}</span>
      ) : null}
    </label>
  )
}

export function Input({ className, ...rest }: ComponentProps<'input'>) {
  return <input className={clsx('field', className)} {...rest} />
}

export function Select({ className, children, ...rest }: ComponentProps<'select'>) {
  return (
    <select className={clsx('field appearance-none pr-8', className)} {...rest}>
      {children}
    </select>
  )
}

export function Textarea({ className, ...rest }: ComponentProps<'textarea'>) {
  return <textarea className={clsx('field min-h-24 font-mono text-xs', className)} {...rest} />
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: ReactNode
  hint?: ReactNode
  disabled?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink-100">{label}</div>
        {hint && <div className="hint mt-0.5">{hint}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors',
          checked ? 'gradient-surface' : 'bg-ink-600',
          disabled && 'opacity-40',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 size-5 rounded-full bg-white shadow transition-all',
            checked ? 'left-[1.4rem]' : 'left-0.5',
          )}
        />
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------- cards */

// Children stay optional: an empty card is how a loading skeleton is drawn.
export function Card({ className, children, ...rest }: ComponentProps<'div'>) {
  return (
    <div className={clsx('glass rounded-2xl', className)} {...rest}>
      {children}
    </div>
  )
}

export function SectionTitle({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-center gap-3">
        {icon && (
          <div className="grid size-10 place-items-center rounded-xl bg-brand-600/15 text-brand-300">
            {icon}
          </div>
        )}
        <div>
          <h2 className="text-xl font-semibold text-ink-100">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-ink-400">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = 'brand',
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: 'brand' | 'accent' | 'success' | 'muted'
}) {
  const tones: Record<string, string> = {
    brand: 'text-brand-300 bg-brand-600/15',
    accent: 'text-accent-300 bg-accent-500/15',
    success: 'text-emerald-300 bg-emerald-500/15',
    muted: 'text-ink-300 bg-ink-600/40',
  }
  return (
    <Card className="flex items-center gap-4 p-4">
      {icon && <div className={clsx('grid size-11 place-items-center rounded-xl', tones[tone])}>{icon}</div>}
      <div className="min-w-0">
        <div className="font-display text-2xl leading-tight text-ink-100">{value}</div>
        <div className="truncate text-xs font-medium uppercase tracking-wide text-ink-400">
          {label}
        </div>
        {hint && <div className="hint mt-0.5 truncate">{hint}</div>}
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------- feedback */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('size-5 animate-spin text-brand-400', className)} aria-hidden />
}

export function CenteredSpinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-ink-400">
      <Spinner className="size-7" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode
  title: ReactNode
  hint?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-ink-600/60 px-6 py-14 text-center">
      {icon && <div className="text-ink-500">{icon}</div>}
      <div className="font-display text-lg text-ink-200">{title}</div>
      {hint && <p className="max-w-md text-sm text-ink-400">{hint}</p>}
      {action}
    </div>
  )
}

export function ProgressBar({
  value,
  className,
  indeterminate = false,
}: {
  value: number
  className?: string
  indeterminate?: boolean
}) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-ink-700/80', className)}>
      {indeterminate ? (
        <div className="progress-indeterminate h-full rounded-full gradient-surface" />
      ) : (
        <div
          className="h-full rounded-full gradient-surface transition-[width] duration-500"
          style={{ width: `${clamped}%` }}
        />
      )}
    </div>
  )
}

export function Chip({
  children,
  className,
  tone,
}: {
  children: ReactNode
  className?: string
  tone?: 'brand' | 'success' | 'warning' | 'danger' | 'muted'
}) {
  const tones: Record<string, string> = {
    brand: 'border-brand-500/40 bg-brand-600/20 text-brand-100',
    success: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-200',
    warning: 'border-amber-500/40 bg-amber-500/15 text-amber-200',
    danger: 'border-accent-500/40 bg-accent-500/15 text-accent-200',
    muted: '',
  }
  return <span className={clsx('chip', tone && tones[tone], className)}>{children}</span>
}

export function Alert({
  tone = 'info',
  children,
  className,
}: {
  tone?: 'info' | 'success' | 'error' | 'warning'
  children: ReactNode
  className?: string
}) {
  const tones: Record<string, string> = {
    info: 'border-brand-500/30 bg-brand-600/10 text-brand-100',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
    error: 'border-accent-500/40 bg-accent-500/10 text-accent-100',
    warning: 'border-amber-500/40 bg-amber-500/10 text-amber-100',
  }
  return (
    <div className={clsx('rounded-xl border px-3.5 py-2.5 text-sm', tones[tone], className)}>
      {children}
    </div>
  )
}

/* --------------------------------------------------------------- overlays */

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-950/70 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <div
        className="absolute inset-0"
        onClick={onClose}
        role="presentation"
        aria-hidden
      />
      <Card
        className={clsx(
          'relative z-10 max-h-[90vh] w-full overflow-y-auto rounded-t-2xl sm:rounded-2xl',
          wide ? 'sm:max-w-3xl' : 'sm:max-w-lg',
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-ink-600/40 px-5 py-4">
          <h3 className="font-display text-lg text-ink-100">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-ghost btn-sm -mr-2 -mt-1"
            aria-label="close"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-ink-600/40 px-5 py-3">{footer}</div>
        )}
      </Card>
    </div>
  )
}

export function Tabs({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: { id: string; label: ReactNode; badge?: ReactNode }[]
  active: string
  onChange: (id: string) => void
  className?: string
}) {
  return (
    <div className={clsx('flex flex-wrap gap-1.5', className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={clsx(
            'btn btn-sm',
            active === tab.id ? 'btn-primary' : 'btn-ghost',
          )}
        >
          {tab.label}
          {tab.badge != null && (
            <span className="ml-1 rounded-full bg-ink-950/40 px-1.5 text-[0.65rem]">{tab.badge}</span>
          )}
        </button>
      ))}
    </div>
  )
}
