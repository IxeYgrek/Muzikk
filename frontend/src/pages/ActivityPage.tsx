import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Activity, Radio, TriangleAlert, Clock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { AlbumCover } from '../components/AlbumCard'
import { INDETERMINATE_STATUSES, StatusBadge } from '../components/StatusBadge'
import { Card, Chip, EmptyState, ProgressBar, StatCard } from '../components/ui'
import { currentLocale } from '../i18n'
import { api } from '../lib/api'
import { formatBytes, formatDateTime, formatEta, formatSpeed } from '../lib/format'
import type { ActivitySnapshot } from '../lib/types'

type EventRow = {
  id: number
  request_id: number
  created_at: string
  level: string
  stage: string
  message: string
  artist: string
  album: string
}

/** Server sent events, with polling as a safety net when the stream drops. */
function useActivityStream() {
  const [snapshot, setSnapshot] = useState<ActivitySnapshot | null>(null)
  const [live, setLive] = useState(false)
  const failures = useRef(0)

  useEffect(() => {
    let source: EventSource | null = null
    let retry: number | undefined
    let closed = false

    const connect = () => {
      source = new EventSource('/api/activity/stream')
      source.onopen = () => {
        failures.current = 0
        setLive(true)
      }
      source.onmessage = (event) => {
        try {
          setSnapshot(JSON.parse(event.data) as ActivitySnapshot)
        } catch {
          /* keep the previous snapshot */
        }
      }
      source.onerror = () => {
        setLive(false)
        source?.close()
        if (closed) return
        failures.current += 1
        if (failures.current <= 5) {
          retry = window.setTimeout(connect, Math.min(30_000, 2000 * failures.current))
        }
      }
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      source?.close()
    }
  }, [])

  const fallback = useQuery({
    queryKey: ['activity', 'summary'],
    queryFn: () => api<ActivitySnapshot>('/activity/summary'),
    refetchInterval: live ? false : 5000,
  })

  return { snapshot: snapshot ?? fallback.data ?? null, live }
}

export function ActivityPage() {
  const { t } = useTranslation()
  const locale = currentLocale()
  const { snapshot, live } = useActivityStream()

  const events = useQuery({
    queryKey: ['activity', 'events'],
    queryFn: () => api<EventRow[]>('/activity/events', { query: { limit: 60 } }),
    refetchInterval: 15_000,
  })

  const items = snapshot?.items ?? []
  const counts = snapshot?.counts

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('activity.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('activity.subtitle')}</p>
        </div>
        <Chip tone={live ? 'success' : 'muted'} className={live ? 'pulse-ring' : undefined}>
          <Radio className="size-3" />
          {live ? t('activity.live') : t('activity.reconnecting')}
        </Chip>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label={t('activity.active')}
          value={counts?.active ?? '—'}
          icon={<Activity className="size-5" />}
        />
        <StatCard
          label={t('activity.pending')}
          value={counts?.pending ?? '—'}
          tone="muted"
          icon={<Clock className="size-5" />}
        />
        <StatCard
          label={t('activity.failed')}
          value={counts?.failed ?? '—'}
          tone="accent"
          icon={<TriangleAlert className="size-5" />}
        />
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon={<Activity className="size-10" />}
          title={t('activity.empty')}
          hint={t('activity.emptyHint')}
        />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Card key={item.id} className="flex flex-wrap items-center gap-3 p-3">
              <AlbumCover
                url={item.cover_url}
                alt={item.album}
                size={250}
                className="size-14 shrink-0 rounded-lg"
              />
              <Link to={`/requests/${item.id}`} className="min-w-40 flex-1">
                <div className="truncate font-semibold text-ink-100">{item.album}</div>
                <div className="truncate text-sm text-ink-400">{item.artist}</div>
                <div className="mt-1.5 flex items-center gap-2">
                  <ProgressBar
                    value={item.progress}
                    className="max-w-64"
                    indeterminate={INDETERMINATE_STATUSES.has(item.status)}
                  />
                  <span className="text-xs tabular-nums text-ink-400">
                    {INDETERMINATE_STATUSES.has(item.status)
                      ? t(`status.${item.status}`, item.status)
                      : `${Math.round(item.progress)} %`}
                  </span>
                </div>
                {item.size > 0 && (
                  <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-ink-500">
                    <span>
                      {formatBytes(item.downloaded)} / {formatBytes(item.size)}
                    </span>
                    <span>
                      {t('activity.speed')} {formatSpeed(item.speed)}
                    </span>
                    <span>
                      {t('activity.eta')} {formatEta(item.eta)}
                    </span>
                  </div>
                )}
              </Link>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <StatusBadge status={item.status} />
                {item.provider && <span className="text-[0.7rem] text-ink-500">{item.provider}</span>}
              </div>
            </Card>
          ))}
        </div>
      )}

      <section>
        <h2 className="mb-3 font-display text-lg text-ink-100">{t('activity.recentEvents')}</h2>
        <Card className="max-h-[28rem] divide-y divide-ink-700/40 overflow-y-auto">
          {(events.data ?? []).map((event) => (
            <Link
              key={event.id}
              to={`/requests/${event.request_id}`}
              className="flex items-start gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-ink-700/25"
            >
              <span
                className={clsx(
                  'mt-1.5 size-2 shrink-0 rounded-full',
                  event.level === 'error'
                    ? 'bg-accent-500'
                    : event.level === 'warning'
                      ? 'bg-amber-400'
                      : 'bg-brand-500',
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-ink-200">{event.message}</div>
                <div className="hint truncate">
                  {event.artist} — {event.album} · {event.stage}
                </div>
              </div>
              <span className="shrink-0 text-xs text-ink-500">
                {formatDateTime(event.created_at, locale)}
              </span>
            </Link>
          ))}
        </Card>
      </section>
    </div>
  )
}
