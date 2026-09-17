export function formatBytes(value: number | null | undefined, decimals = 1): string {
  if (!value || value <= 0) return '0 o'
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)))
  const size = value / Math.pow(1024, index)
  return `${size.toFixed(index === 0 ? 0 : decimals)} ${units[index]}`
}

export function formatSpeed(bytesPerSecond: number | null | undefined): string {
  if (!bytesPerSecond || bytesPerSecond <= 0) return '—'
  return `${formatBytes(bytesPerSecond)}/s`
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '—'
  const total = Math.round(ms / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

/** Playback clock, in seconds, always shown even at zero. */
export function formatClock(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(seconds ?? 0))
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

export function formatEta(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0 || seconds > 86400 * 30) return '—'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, '0')}`
  if (minutes > 0) return `${minutes} min`
  return `${Math.round(seconds)} s`
}

/** The API serialises naive UTC timestamps, so a missing offset means UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  const date = new Date(hasZone || !value.includes('T') ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDate(value: string | null | undefined, locale = 'fr-FR'): string {
  const date = parseDate(value)
  if (!date) return '—'
  return date.toLocaleDateString(locale, { day: '2-digit', month: 'short', year: 'numeric' })
}

export function formatDateTime(value: string | null | undefined, locale = 'fr-FR'): string {
  const date = parseDate(value)
  if (!date) return '—'
  return date.toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(value: string | null | undefined, locale = 'fr-FR'): string {
  const date = parseDate(value)
  if (!date) return '—'
  const diff = date.getTime() - Date.now()
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 31536000000],
    ['month', 2592000000],
    ['day', 86400000],
    ['hour', 3600000],
    ['minute', 60000],
  ]
  for (const [unit, amount] of units) {
    if (Math.abs(diff) >= amount) {
      return formatter.format(Math.round(diff / amount), unit)
    }
  }
  return formatter.format(Math.round(diff / 1000), 'second')
}
