import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowUpCircle,
  Ban,
  Check,
  Inbox,
  Pause,
  Play,
  RotateCcw,
  ScanSearch,
  Trash2,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { AlbumCover } from '../components/AlbumCard'
import { ACTIVE_STATUSES, INDETERMINATE_STATUSES, StatusBadge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import {
  Button,
  Card,
  CenteredSpinner,
  Chip,
  EmptyState,
  Modal,
  ProgressBar,
  Tabs,
} from '../components/ui'
import { currentLocale } from '../i18n'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  formatBytes,
  formatClock,
  formatDateTime,
  formatEta,
  formatSpeed,
  relativeTime,
} from '../lib/format'
import { usePlayer } from '../lib/player'
import type {
  AlbumRequest,
  PlayableTrack,
  RequestDetail,
  RequestListResponse,
  UpgradeFile,
  UpgradeReview,
} from '../lib/types'

/** Containers the in-app player can decode without Jellyfin. */
const BROWSER_AUDIO = new Set(['flac', 'mp3', 'm4a', 'aac', 'ogg', 'opus', 'wav', 'webm', 'weba'])

/** Everything the "cancel active requests" button reaches, as the API sees it. */
const OPEN_STATUSES = new Set(['pending', 'approved', ...ACTIVE_STATUSES])

type BulkAction = 'imported' | 'failed' | 'cancel' | 'retry'

/** Method and path of each bulk action, since they are not all deletions. */
const BULK_ROUTES: Record<BulkAction, { path: string; method: 'POST' | 'DELETE' }> = {
  imported: { path: '/requests/imported', method: 'DELETE' },
  failed: { path: '/requests/failed', method: 'DELETE' },
  cancel: { path: '/requests/cancel-active', method: 'POST' },
  retry: { path: '/requests/retry-failed', method: 'POST' },
}

export function RequestsPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { notify } = useToast()

  const [scope, setScope] = useState<'mine' | 'all' | 'moderation'>(
    user?.is_admin ? 'all' : 'mine',
  )
  const [statusFilter, setStatusFilter] = useState('')

  const list = useQuery({
    queryKey: ['requests', scope, statusFilter],
    queryFn: () =>
      api<RequestListResponse>('/requests', {
        query: {
          mine: scope === 'mine' || undefined,
          status: scope === 'moderation' ? 'pending' : statusFilter || undefined,
          limit: 100,
        },
      }),
    refetchInterval: 10_000,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['requests'] })
    void queryClient.invalidateQueries({ queryKey: ['activity'] })
  }

  const action = useMutation({
    mutationFn: async ({ requestId, kind }: { requestId: number; kind: string }) => {
      if (kind === 'delete') {
        await api(`/requests/${requestId}`, { method: 'DELETE' })
        return
      }
      await api(`/requests/${requestId}/${kind}`, { method: 'POST' })
    },
    onSuccess: (_data, variables) => {
      const messages: Record<string, string> = {
        approve: t('requests.approved'),
        reject: t('requests.rejectedToast'),
        cancel: t('requests.cancelled'),
        retry: t('requests.retried'),
        delete: t('requests.deleted'),
      }
      notify(messages[variables.kind] ?? t('common.saved'), 'success')
      invalidate()
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const bulk = useMutation({
    mutationFn: (action: BulkAction) => {
      const route = BULK_ROUTES[action]
      return api<{ removed?: number; cancelled?: number; requeued?: number }>(route.path, {
        method: route.method,
      })
    },
    onSuccess: (result, action) => {
      const count = result.removed ?? result.cancelled ?? result.requeued ?? 0
      const messages: Record<BulkAction, string> = {
        imported: t('requests.clearedImported', { count }),
        failed: t('requests.clearedFailed', { count }),
        cancel: t('requests.cancelledActive', { count }),
        retry: t('requests.retriedFailed', { count }),
      }
      notify(messages[action], 'success')
      invalidate()
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const runBulk = (action: BulkAction, prompt: string) => {
    if (!window.confirm(prompt)) return
    bulk.mutate(action)
  }

  const items = list.data?.items ?? []
  const importedCount = items.filter((request) => request.status === 'imported').length
  const failedCount = items.filter((request) => request.status === 'failed').length
  const openCount = items.filter((request) => OPEN_STATUSES.has(request.status)).length

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('requests.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('requests.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {openCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              loading={bulk.isPending && bulk.variables === 'cancel'}
              onClick={() => runBulk('cancel', t('requests.confirmCancelActive'))}
            >
              <Ban className="size-3.5" />
              {t('requests.cancelActive')}
            </Button>
          )}
          {failedCount > 0 && (
            <>
              <Button
                variant="secondary"
                size="sm"
                loading={bulk.isPending && bulk.variables === 'retry'}
                onClick={() => runBulk('retry', t('requests.confirmRetryFailed'))}
              >
                <RotateCcw className="size-3.5" />
                {t('requests.retryFailed')}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={bulk.isPending && bulk.variables === 'failed'}
                onClick={() => runBulk('failed', t('requests.confirmClearFailed'))}
              >
                <Trash2 className="size-3.5" />
                {t('requests.clearFailed')}
              </Button>
            </>
          )}
          {importedCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              loading={bulk.isPending && bulk.variables === 'imported'}
              onClick={() => runBulk('imported', t('requests.confirmClearImported'))}
            >
              <Trash2 className="size-3.5" />
              {t('requests.clearImported')}
            </Button>
          )}
        </div>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          active={scope}
          onChange={(value) => setScope(value as typeof scope)}
          tabs={
            user?.is_admin
              ? [
                  { id: 'all', label: t('requests.all') },
                  { id: 'mine', label: t('requests.mine') },
                  { id: 'moderation', label: t('requests.moderation') },
                ]
              : [{ id: 'mine', label: t('requests.mine') }]
          }
        />

        {scope !== 'moderation' && (
          <Tabs
            active={statusFilter}
            onChange={setStatusFilter}
            tabs={[
              { id: '', label: t('common.all') },
              { id: 'open', label: t('activity.active') },
              { id: 'awaiting_validation', label: t('status.awaiting_validation') },
              { id: 'imported', label: t('status.imported') },
              { id: 'failed', label: t('status.failed') },
            ]}
          />
        )}
      </div>

      {list.isLoading ? (
        <CenteredSpinner />
      ) : items.length === 0 ? (
        <EmptyState icon={<Inbox className="size-10" />} title={t('requests.empty')} />
      ) : (
        <div className="space-y-2">
          {items.map((request) => (
            <RequestRow
              key={request.id}
              request={request}
              isAdmin={Boolean(user?.is_admin)}
              onOpen={() => navigate(`/requests/${request.id}`)}
              onAction={(kind) => {
                if (kind === 'delete' && !window.confirm(t('requests.confirmDelete'))) return
                action.mutate({ requestId: request.id, kind })
              }}
              busy={action.isPending}
            />
          ))}
        </div>
      )}

      {id && (
        <RequestDetailModal
          requestId={Number(id)}
          onClose={() => navigate('/requests')}
          isAdmin={Boolean(user?.is_admin)}
        />
      )}
    </div>
  )
}

function RequestRow({
  request,
  isAdmin,
  onOpen,
  onAction,
  busy,
}: {
  request: AlbumRequest
  isAdmin: boolean
  onOpen: () => void
  onAction: (kind: string) => void
  busy: boolean
}) {
  const { t } = useTranslation()
  const active = ACTIVE_STATUSES.has(request.status)
  const waiting = INDETERMINATE_STATUSES.has(request.status)

  return (
    <Card className="flex flex-wrap items-center gap-3 p-3 transition-colors hover:border-brand-500/30">
      <button type="button" onClick={onOpen} className="shrink-0">
        <AlbumCover
          url={request.cover_url}
          alt={request.album_title}
          size={250}
          className="size-14 rounded-lg"
        />
      </button>

      <button type="button" onClick={onOpen} className="min-w-40 flex-1 text-left">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold text-ink-100">{request.album_title}</span>
          {request.is_upgrade && (
            <Chip tone="warning">
              <ArrowUpCircle className="size-3" />
              {t('requests.upgrade')}
            </Chip>
          )}
        </div>
        <div className="truncate text-sm text-ink-400">
          {request.artist_name}
          {request.year ? ` · ${request.year}` : ''}
        </div>
        {active && (
          <div className="mt-1.5 flex items-center gap-2">
            <ProgressBar
              value={request.progress}
              className="max-w-52"
              indeterminate={waiting}
            />
            <span className="text-xs tabular-nums text-ink-400">
              {waiting
                ? t(`status.${request.status}`, request.status)
                : `${Math.round(request.progress)} %`}
            </span>
          </div>
        )}
        {request.error && request.status === 'failed' && (
          <div className="mt-1 truncate text-xs text-accent-300">{request.error}</div>
        )}
      </button>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <StatusBadge status={request.status} />
        <span className="text-[0.7rem] text-ink-500">
          {request.user_name ? `${request.user_name} · ` : ''}
          {relativeTime(request.created_at, currentLocale())}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {isAdmin && request.status === 'pending' && (
          <>
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={() => onAction('approve')}
              title={t('requests.approve')}
            >
              <Check className="size-3.5" />
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() => onAction('reject')}
              title={t('requests.reject')}
            >
              <X className="size-3.5" />
            </Button>
          </>
        )}
        {request.status === 'awaiting_validation' && (
          <Button size="sm" variant="primary" onClick={onOpen} title={t('requests.review.open')}>
            <ScanSearch className="size-3.5" />
          </Button>
        )}
        {request.status === 'failed' && (
          <Button size="sm" disabled={busy} onClick={() => onAction('retry')} title={t('requests.retry')}>
            <RotateCcw className="size-3.5" />
          </Button>
        )}
        {!['imported', 'cancelled', 'rejected', 'failed', 'awaiting_validation'].includes(
          request.status,
        ) && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onAction('cancel')}
            title={t('requests.cancelRequest')}
          >
            <Ban className="size-3.5" />
          </Button>
        )}
        {isAdmin && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onAction('delete')}
            title={t('requests.deleteRequest')}
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>
    </Card>
  )
}

function RequestDetailModal({
  requestId,
  onClose,
  isAdmin,
}: {
  requestId: number
  onClose: () => void
  isAdmin: boolean
}) {
  const { t } = useTranslation()
  const locale = currentLocale()
  const queryClient = useQueryClient()
  const { notify } = useToast()

  const detail = useQuery({
    queryKey: ['requests', 'detail', requestId],
    queryFn: () => api<RequestDetail>(`/requests/${requestId}`),
    refetchInterval: 5000,
  })

  const decide = useMutation({
    mutationFn: (accept: boolean) =>
      api(`/requests/${requestId}/upgrade/${accept ? 'confirm' : 'refuse'}`, { method: 'POST' }),
    onSuccess: (_result, accept) => {
      notify(t(accept ? 'requests.review.accepted' : 'requests.review.refused'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['requests'] })
      void queryClient.invalidateQueries({ queryKey: ['library'] })
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const request = detail.data

  return (
    <Modal open onClose={onClose} wide title={t('requests.detail')}>
      {!request ? (
        <CenteredSpinner />
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-start gap-4">
            <AlbumCover
              url={request.cover_url}
              alt={request.album_title}
              size={500}
              className="size-24 shrink-0 rounded-xl"
            />
            <div className="min-w-0 flex-1">
              <h3 className="font-display text-xl text-ink-100">{request.album_title}</h3>
              <p className="text-sm text-ink-400">{request.artist_name}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusBadge status={request.status} />
                {request.provider_label && <Chip tone="brand">{request.provider_label}</Chip>}
                {request.is_upgrade && <Chip tone="warning">{t('requests.upgrade')}</Chip>}
                <Chip>
                  {t('requests.attempts')} {request.attempts}
                </Chip>
              </div>
              {request.destination_path && (
                <p className="hint mt-2 break-all">
                  {t('requests.importedTo')} {request.destination_path}
                </p>
              )}
              {request.error && <p className="mt-2 text-sm text-accent-300">{request.error}</p>}
              {request.retry_after && (
                <p className="hint mt-1">
                  {t('requests.nextRetry')} {relativeTime(request.retry_after, locale)}
                </p>
              )}
            </div>
          </div>

          {request.upgrade_review && (
            <UpgradeReviewPanel
              requestId={request.id}
              artist={request.artist_name}
              album={request.album_title}
              coverUrl={request.cover_url}
              review={request.upgrade_review}
              pending={request.status === 'awaiting_validation'}
              busy={decide.isPending}
              onDecide={(accept) => decide.mutate(accept)}
            />
          )}

          {request.downloads.length > 0 && (
            <section>
              <h4 className="label">{t('requests.downloads')}</h4>
              <div className="space-y-2">
                {request.downloads.map((download) => (
                  <div key={download.id} className="rounded-xl bg-ink-800/50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span className="font-medium text-ink-200">
                        {download.client}
                        {download.username ? ` · ${download.username}` : ''}
                      </span>
                      <span className="text-xs text-ink-400">{download.state}</span>
                    </div>
                    <ProgressBar value={download.progress} className="my-2" />
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-400">
                      <span>
                        {formatBytes(download.downloaded)} / {formatBytes(download.size)}
                      </span>
                      <span>
                        {t('activity.speed')} {formatSpeed(download.speed)}
                      </span>
                      <span>
                        {t('activity.eta')} {formatEta(download.eta)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h4 className="label">{t('requests.candidates')}</h4>
            {request.attempts_log.length === 0 ? (
              <p className="hint">{t('requests.noCandidates')}</p>
            ) : (
              <div className="space-y-1.5">
                {request.attempts_log.map((attempt) => (
                  <div
                    key={attempt.id}
                    className={clsx(
                      'rounded-xl border px-3 py-2 text-sm',
                      attempt.decision === 'accepted'
                        ? 'border-emerald-500/30 bg-emerald-500/5'
                        : 'border-ink-600/40 bg-ink-800/40',
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-ink-200" title={attempt.candidate_title}>
                        {attempt.candidate_title}
                      </span>
                      <Chip tone={attempt.decision === 'accepted' ? 'success' : 'muted'}>
                        {t('requests.score')} {attempt.score.toFixed(1)}
                      </Chip>
                    </div>
                    <div className="hint mt-0.5">
                      {attempt.provider_label} ·{' '}
                      {attempt.decision === 'accepted' ? t('requests.accepted') : t('requests.rejected')}
                      {attempt.reason ? ` · ${attempt.reason}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h4 className="label">{t('requests.timeline')}</h4>
            <ol className="space-y-2 border-l border-ink-600/50 pl-4">
              {[...request.events].reverse().map((event) => (
                <li key={event.id} className="relative">
                  <span
                    className={clsx(
                      'absolute -left-[1.32rem] top-1.5 size-2 rounded-full',
                      event.level === 'error'
                        ? 'bg-accent-500'
                        : event.level === 'warning'
                          ? 'bg-amber-400'
                          : 'bg-brand-500',
                    )}
                  />
                  <div className="text-sm text-ink-200">{event.message}</div>
                  <div className="hint">
                    {event.stage} · {formatDateTime(event.created_at, locale)}
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {isAdmin && request.user_name && (
            <p className="hint">
              {t('requests.requestedBy')} {request.user_name}
            </p>
          )}
        </div>
      )}
    </Modal>
  )
}

function UpgradeReviewPanel({
  requestId,
  artist,
  album,
  coverUrl,
  review,
  pending,
  busy,
  onDecide,
}: {
  requestId: number
  artist: string
  album: string
  coverUrl: string | null
  review: UpgradeReview
  pending: boolean
  busy: boolean
  onDecide: (accept: boolean) => void
}) {
  const { t } = useTranslation()
  const missing = review.old_files.length - review.new_files.length
  const meta = { artist, album, coverUrl }

  return (
    <section className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="label mb-0">{t('requests.review.title')}</h4>
        {review.resolved && (
          <Chip tone={review.resolved === 'accepted' ? 'success' : 'danger'}>
            {t(`requests.review.${review.resolved}`)} ·{' '}
            {t('requests.review.done', { count: review.removed?.length ?? 0 })}
          </Chip>
        )}
      </div>
      {pending && <p className="hint mt-1">{t('requests.review.hint')}</p>}

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <UpgradeSide
          title={t('requests.review.before')}
          path={review.old_path}
          files={review.old_files}
          requestId={requestId}
          side="old"
          meta={meta}
        />
        <UpgradeSide
          title={t('requests.review.after')}
          path={review.new_path}
          files={review.new_files}
          requestId={requestId}
          side="new"
          meta={meta}
          highlight
        />
      </div>

      {missing > 0 && (
        <p className="mt-2 text-sm text-amber-300">{t('requests.review.missing', { count: missing })}</p>
      )}
      {review.same_folder && <p className="hint mt-2">{t('requests.review.sameFolder')}</p>}

      {pending && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            loading={busy}
            onClick={() => {
              const count = review.remove.length
              if (!window.confirm(t('requests.review.confirmPrompt', { count }))) return
              onDecide(true)
            }}
          >
            <Check className="size-3.5" />
            {t('requests.review.confirm')}
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={busy}
            onClick={() => {
              const count = review.new_files.length
              if (!window.confirm(t('requests.review.refusePrompt', { count }))) return
              onDecide(false)
            }}
          >
            <X className="size-3.5" />
            {t('requests.review.refuse')}
          </Button>
          <span className="hint">
            {t('requests.review.toRemove', { count: review.remove.length })}
          </span>
        </div>
      )}
    </section>
  )
}

function UpgradeSide({
  title,
  path,
  files,
  requestId,
  side,
  meta,
  highlight = false,
}: {
  title: string
  path: string | null
  files: UpgradeFile[]
  requestId: number
  side: 'old' | 'new'
  meta: { artist: string; album: string; coverUrl: string | null }
  highlight?: boolean
}) {
  const { t } = useTranslation()
  const player = usePlayer()
  const size = files.reduce((total, file) => total + (file.size || 0), 0)
  const formats = [...new Set(files.map((file) => file.format).filter(Boolean))]
  const queue = upgradeQueue(requestId, side, files, meta)
  const prefix = `/api/play/upgrade/${requestId}/${side}/`
  const sideActive = Boolean(player.current?.stream_url.startsWith(prefix))

  return (
    <div className="min-w-0 rounded-xl bg-ink-800/50 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {queue.length > 0 && (
            <UpgradePlayButton
              active={sideActive}
              playing={player.playing}
              label={t('requests.review.playVersion')}
              onPlay={() => player.playTracks(queue, 0)}
              onToggle={player.toggle}
            />
          )}
          <span className="text-sm font-semibold text-ink-200">{title}</span>
        </div>
        <Chip tone={highlight ? 'success' : 'muted'}>
          {formats.map((format) => format.toUpperCase()).join(', ') || '—'}
        </Chip>
      </div>
      <p className="hint mt-0.5 break-all">{path || '—'}</p>
      <p className="hint">
        {t('requests.review.summary', { count: files.length, size: formatBytes(size) })}
      </p>
      <ol className="mt-2 max-h-64 space-y-1 overflow-y-auto pr-1">
        {files.map((file, index) => {
          const track = queue.find((item) => item.stream_url === `${prefix}${index}`)
          const trackActive = player.current?.stream_url === `${prefix}${index}`
          return (
            <li key={file.path} className="flex items-center gap-2 text-xs">
              {track ? (
                <UpgradePlayButton
                  active={trackActive}
                  playing={player.playing}
                  label={t('requests.review.playTrack', { title: file.title || file.name })}
                  onPlay={() => player.playTracks(queue, queue.indexOf(track))}
                  onToggle={player.toggle}
                />
              ) : (
                <span className="size-7 shrink-0" />
              )}
              <span className="w-5 shrink-0 text-right tabular-nums text-ink-500">
                {file.track ?? '—'}
              </span>
              <span className="min-w-0 flex-1 truncate text-ink-200" title={file.name}>
                {file.title || file.name}
              </span>
              <span className="shrink-0 tabular-nums text-ink-400">{quality(file)}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function UpgradePlayButton({
  active,
  playing,
  label,
  onPlay,
  onToggle,
}: {
  active: boolean
  playing: boolean
  label: string
  onPlay: () => void
  onToggle: () => void
}) {
  const { t } = useTranslation()
  const listening = active && playing
  return (
    <button
      type="button"
      className={clsx(
        'grid size-7 shrink-0 place-items-center rounded-full transition-colors',
        listening
          ? 'bg-brand-500 text-white'
          : 'bg-ink-700/80 text-ink-200 hover:bg-ink-600 hover:text-white',
      )}
      title={listening ? t('player.pause') : label}
      aria-label={listening ? t('player.pause') : label}
      onClick={() => (active ? onToggle() : onPlay())}
    >
      {listening ? <Pause className="size-3.5" /> : <Play className="ml-px size-3.5" />}
    </button>
  )
}

function upgradeQueue(
  requestId: number,
  side: 'old' | 'new',
  files: UpgradeFile[],
  meta: { artist: string; album: string; coverUrl: string | null },
): PlayableTrack[] {
  return files.flatMap((file, index) => {
    if (!BROWSER_AUDIO.has(file.format.toLowerCase())) return []
    return [
      {
        jellyfin_id: '',
        title: file.title || file.name,
        artist: meta.artist,
        album: meta.album,
        album_id: null,
        track: file.track,
        disc: null,
        duration: file.duration,
        container: file.format,
        cover_url: meta.coverUrl,
        stream_url: `/api/play/upgrade/${requestId}/${side}/${index}`,
      },
    ]
  })
}

/** Format, resolution and length, as a listener would compare two copies. */
function quality(file: UpgradeFile): string {
  const parts: string[] = []
  if (file.bit_depth && file.sample_rate) {
    parts.push(`${file.bit_depth} bit ${Math.round(file.sample_rate / 1000)} kHz`)
  } else if (file.bitrate) {
    parts.push(`${Math.round(file.bitrate / 1000)} kb/s`)
  }
  if (file.duration) parts.push(formatClock(file.duration))
  return parts.join(' · ')
}
