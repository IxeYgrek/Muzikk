import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle,
  Copy,
  CopyMinus,
  Disc3,
  EyeOff,
  Image as ImageIcon,
  ImageUp,
  Images,
  RefreshCw,
  Replace,
  ScanSearch,
  Search,
  ServerCog,
  Sparkles,
  Tags,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AlbumCover } from '../components/AlbumCard'
import { MetadataAlbumPanel } from '../components/MetadataAlbumPanel'
import { useToast } from '../components/Toast'
import {
  Alert,
  Button,
  Card,
  CenteredSpinner,
  Chip,
  EmptyState,
  Input,
  Modal,
  Select,
  StatCard,
} from '../components/ui'
import { ApiError, api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { useLocalMode } from '../lib/hooks'
import type {
  ArtworkSyncReport,
  JellyfinCoverReport,
  JellyfinMetadataReport,
  MetadataAlbum,
  MetadataListResponse,
  MetadataScanReport,
  MetadataSummary,
} from '../lib/types'

const PAGE_SIZE = 40

const ISSUE_ORDER = [
  'not_in_jellyfin',
  'missing_mbid',
  'probable_match',
  'missing_cover',
  'incomplete_tags',
  'duplicate_tags',
  'duplicate',
] as const

const ISSUE_ICONS: Record<string, typeof Tags> = {
  not_in_jellyfin: ServerCog,
  missing_mbid: Tags,
  probable_match: Sparkles,
  missing_cover: ImageIcon,
  incomplete_tags: AlertTriangle,
  duplicate_tags: CopyMinus,
  duplicate: Copy,
}

export function MetadataPage() {
  const { t } = useTranslation()
  const { notify } = useToast()
  const queryClient = useQueryClient()
  const localMode = useLocalMode()
  const issueKinds = ISSUE_ORDER.filter((kind) => kind !== 'not_in_jellyfin' || !localMode)

  const [issue, setIssue] = useState('')
  const [state, setState] = useState('open')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)

  // Typing in the box should not fire one request per keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim())
      setOffset(0)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [search])

  const summary = useQuery({
    queryKey: ['metadata', 'summary'],
    queryFn: () => api<MetadataSummary>('/metadata/summary'),
    // While a background pass runs, keep the counters moving.
    refetchInterval: (result) => {
      const data = result.state.data
      const busy =
        data?.scan_running ||
        data?.artwork_running ||
        data?.jellyfin_covers_running ||
        data?.jellyfin_meta_running
      return busy ? 4_000 : false
    },
  })

  const albums = useQuery({
    queryKey: ['metadata', 'albums', issue, state, query, offset],
    queryFn: () =>
      api<MetadataListResponse>('/metadata/albums', {
        query: {
          issue: issue || undefined,
          state,
          q: query || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      }),
  })

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const scan = useMutation({
    mutationFn: () => api<{ queued: boolean }>('/metadata/scan', { method: 'POST' }),
    onSuccess: (result) => {
      notify(result.queued ? t('metadata.scanQueued') : t('metadata.scanAlready'), 'info')
      void summary.refetch()
    },
    onError: fail,
  })

  const refreshJellyfin = useMutation({
    mutationFn: () => api('/metadata/jellyfin-refresh', { method: 'POST' }),
    onSuccess: () => notify(t('metadata.jellyfinRefreshQueued'), 'success'),
    onError: fail,
  })

  const artworkSync = useMutation({
    mutationFn: () => api<{ queued: boolean }>('/metadata/artwork-sync', { method: 'POST' }),
    onSuccess: (result) => {
      notify(result.queued ? t('metadata.artworkQueued') : t('metadata.artworkAlready'), 'info')
      void summary.refetch()
    },
    onError: fail,
  })

  const jellyfinCovers = useMutation({
    mutationFn: () => api<{ queued: boolean }>('/metadata/jellyfin-covers', { method: 'POST' }),
    onSuccess: (result) => {
      notify(result.queued ? t('metadata.coversQueued') : t('metadata.coversAlready'), 'info')
      void summary.refetch()
    },
    onError: fail,
  })

  const jellyfinMeta = useMutation({
    mutationFn: () => api<{ queued: boolean }>('/metadata/jellyfin-metadata', { method: 'POST' }),
    onSuccess: (result) => {
      notify(result.queued ? t('metadata.alignQueued') : t('metadata.alignAlready'), 'info')
      void summary.refetch()
    },
    onError: fail,
  })

  const scanning = summary.data?.scan_running ?? false
  const pairing = summary.data?.artwork_running ?? false
  const repairing = summary.data?.jellyfin_covers_running ?? false
  const aligning = summary.data?.jellyfin_meta_running ?? false
  const items = albums.data?.items ?? []
  const total = albums.data?.count ?? 0

  // A finished analysis has to show up in the list too, but only refetch on the
  // transition: invalidating on every render would fight the list query.
  const wasScanning = useRef(false)
  useEffect(() => {
    if (wasScanning.current && !scanning) {
      void queryClient.invalidateQueries({ queryKey: ['metadata', 'albums'] })
    }
    wasScanning.current = scanning
  }, [queryClient, scanning])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-bold text-ink-100">{t('metadata.title')}</h1>
          <p className="mt-1 text-sm text-ink-400">{t('metadata.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!localMode && (
            <Button
              variant="secondary"
              size="sm"
              loading={refreshJellyfin.isPending}
              onClick={() => refreshJellyfin.mutate()}
              title={t('metadata.jellyfinRefreshHint')}
            >
              <RefreshCw className="size-3.5" />
              {t('metadata.jellyfinRefresh')}
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            loading={artworkSync.isPending || pairing}
            onClick={() => artworkSync.mutate()}
            title={t('metadata.artworkHint')}
          >
            <Images className="size-3.5" />
            {pairing ? t('metadata.artworkRunning') : t('metadata.artwork')}
          </Button>
          {!localMode && (
            <>
              <Button
                variant="secondary"
                size="sm"
                loading={jellyfinCovers.isPending || repairing}
                onClick={() => jellyfinCovers.mutate()}
                title={t('metadata.coversHint')}
              >
                <ImageUp className="size-3.5" />
                {repairing ? t('metadata.coversRunning') : t('metadata.covers')}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={jellyfinMeta.isPending || aligning}
                onClick={() => jellyfinMeta.mutate()}
                title={t('metadata.alignHint')}
              >
                <Replace className="size-3.5" />
                {aligning ? t('metadata.alignRunning') : t('metadata.align')}
              </Button>
            </>
          )}
          <Button
            variant="primary"
            size="sm"
            loading={scan.isPending || scanning}
            onClick={() => scan.mutate()}
          >
            <ScanSearch className="size-3.5" />
            {scanning ? t('metadata.scanning') : t('metadata.scan')}
          </Button>
        </div>
      </header>

      {summary.data && !summary.data.library_readable && (
        <Alert tone="error">
          {t('metadata.libraryUnreadable', { path: summary.data.library_dir })}
        </Alert>
      )}

      {summary.data?.last_error && !scanning && (
        <Alert tone="error">
          <span className="font-semibold">{t('metadata.scanFailed')}</span>{' '}
          <span className="break-words">{summary.data.last_error}</span>
        </Alert>
      )}

      {summary.data && summary.data.total === 0 && !scanning && !summary.data.last_error && (
        <Alert tone="info">{t('metadata.neverScanned')}</Alert>
      )}

      {/* Where every folder went, so the analysed count needs no guessing. */}
      {summary.data && summary.data.total > 0 && !scanning && (
        <Alert tone={reportTone(summary.data.last_scan)}>
          {summary.data.last_scan ? (
            <ScanReport report={summary.data.last_scan} />
          ) : (
            t('metadata.reportMissing')
          )}
        </Alert>
      )}

      {summary.data?.artwork_error && !pairing && (
        <Alert tone="error">
          <span className="font-semibold">{t('metadata.artworkFailed')}</span>{' '}
          <span className="break-words">{summary.data.artwork_error}</span>
        </Alert>
      )}

      {summary.data?.last_artwork_sync && !pairing && !summary.data.artwork_error && (
        <Alert tone={summary.data.last_artwork_sync.failed > 0 ? 'warning' : 'info'}>
          <ArtworkReport report={summary.data.last_artwork_sync} />
        </Alert>
      )}

      {!localMode && summary.data?.jellyfin_covers_error && !repairing && (
        <Alert tone="error">
          <span className="font-semibold">{t('metadata.coversFailed')}</span>{' '}
          <span className="break-words">{summary.data.jellyfin_covers_error}</span>
        </Alert>
      )}

      {!localMode && summary.data?.last_jellyfin_covers && !repairing && !summary.data.jellyfin_covers_error && (
        <Alert tone={summary.data.last_jellyfin_covers.failed > 0 ? 'warning' : 'info'}>
          <CoverRepairReport report={summary.data.last_jellyfin_covers} />
        </Alert>
      )}

      {!localMode && summary.data?.jellyfin_meta_error && !aligning && (
        <Alert tone="error">
          <span className="font-semibold">{t('metadata.alignFailed')}</span>{' '}
          <span className="break-words">{summary.data.jellyfin_meta_error}</span>
        </Alert>
      )}

      {!localMode && summary.data?.last_jellyfin_meta && !aligning && !summary.data.jellyfin_meta_error && (
        <Alert tone={summary.data.last_jellyfin_meta.failed > 0 ? 'warning' : 'info'}>
          <AlignReport report={summary.data.last_jellyfin_meta} />
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
        <StatCard
          label={t('metadata.stat.open')}
          value={summary.data?.open ?? '—'}
          icon={<AlertTriangle className="size-5" />}
          tone="accent"
          hint={
            summary.data?.last_scan_at
              ? t('metadata.lastScan', { when: relativeTime(summary.data.last_scan_at) })
              : undefined
          }
        />
        <StatCard
          label={t('metadata.stat.albums')}
          value={summary.data?.total ?? '—'}
          icon={<Disc3 className="size-5" />}
          tone="brand"
          hint={
            summary.data?.library_albums
              ? t(localMode ? 'metadata.inLibrary' : 'metadata.inJellyfin', {
                  count: summary.data.library_albums,
                })
              : undefined
          }
        />
        <StatCard
          label={t('metadata.stat.resolved')}
          value={summary.data?.resolved ?? '—'}
          icon={<Sparkles className="size-5" />}
          tone="success"
        />
        <StatCard
          label={t('metadata.stat.ignored')}
          value={summary.data?.ignored ?? '—'}
          icon={<EyeOff className="size-5" />}
          tone="muted"
        />
      </div>

      {summary.data && !summary.data.fingerprinting_available && (
        <Alert tone="warning">{t('metadata.noFpcalc')}</Alert>
      )}
      {summary.data?.fingerprinting_available && !summary.data.acoustid_configured && (
        <Alert tone="info">{t('metadata.noAcoustidKey')}</Alert>
      )}

      {/* Issue buckets double as the main filter. */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            setIssue('')
            setOffset(0)
          }}
          className={clsx('btn btn-sm', issue === '' ? 'btn-primary' : 'btn-secondary')}
        >
          {t('metadata.allIssues')}
          <span className="ml-1 rounded-full bg-ink-950/40 px-1.5 text-[0.65rem]">
            {summary.data?.open ?? 0}
          </span>
        </button>
        {issueKinds.map((kind) => {
          const Icon = ISSUE_ICONS[kind]
          const count = summary.data?.issues?.[kind] ?? 0
          return (
            <button
              key={kind}
              type="button"
              onClick={() => {
                setIssue(kind)
                setOffset(0)
              }}
              className={clsx('btn btn-sm', issue === kind ? 'btn-primary' : 'btn-secondary')}
            >
              <Icon className="size-3.5" />
              {t(`metadata.issue.${kind}`)}
              <span className="ml-1 rounded-full bg-ink-950/40 px-1.5 text-[0.65rem]">{count}</span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-500" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('metadata.searchPlaceholder')}
            className="pl-9"
          />
        </div>
        <Select
          value={state}
          onChange={(event) => {
            setState(event.target.value)
            setOffset(0)
          }}
          className="w-auto"
        >
          <option value="open">{t('metadata.stateOpen')}</option>
          <option value="resolved">{t('metadata.stateResolved')}</option>
          <option value="ignored">{t('metadata.stateIgnored')}</option>
          <option value="any">{t('metadata.stateAny')}</option>
        </Select>
      </div>

      {albums.isLoading ? (
        <CenteredSpinner label={t('common.loading')} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Tags className="size-10" />}
          title={t('metadata.emptyTitle')}
          hint={t('metadata.emptyHint')}
        />
      ) : (
        <Card className="divide-y divide-ink-700/40 overflow-hidden">
          {items.map((album) => (
            <AlbumRow key={album.id} album={album} onOpen={() => setSelected(album.id)} />
          ))}
        </Card>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-3">
          <Button
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            {t('common.previous')}
          </Button>
          <span className="text-xs text-ink-400">
            {t('metadata.pageRange', {
              from: offset + 1,
              to: Math.min(offset + PAGE_SIZE, total),
              total,
            })}
          </span>
          <Button
            size="sm"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            {t('common.next')}
          </Button>
        </div>
      )}

      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={t('metadata.panelTitle')}
        wide
      >
        {selected !== null && (
          <MetadataAlbumPanel albumId={selected} onClose={() => setSelected(null)} />
        )}
      </Modal>
    </div>
  )
}

/** A report with nothing left behind is plain information. */
function reportTone(report: MetadataScanReport | null): 'info' | 'warning' {
  if (!report) return 'warning'
  return report.failed + report.unreadable > 0 ? 'warning' : 'info'
}

/** One sentence explaining what the walk found and what it left behind. */
function ScanReport({ report }: { report: MetadataScanReport }) {
  const { t } = useTranslation()

  const parts = [
    t('metadata.report.found', { count: report.folders, path: report.root }),
    t('metadata.report.analysed', { count: report.analysed }),
  ]
  if (report.below_min_tracks > 0) {
    parts.push(
      t('metadata.report.belowMinTracks', {
        count: report.below_min_tracks,
        min: report.min_tracks,
      }),
    )
  }
  if (report.unreadable > 0) {
    parts.push(t('metadata.report.unreadable', { count: report.unreadable }))
  }
  if (report.failed > 0) {
    parts.push(t('metadata.report.failed', { count: report.failed }))
  }

  return (
    <div className="space-y-1">
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.report.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {parts.join(' · ')}
      </div>

      {report.failures.length > 0 && (
        <ul className="space-y-0.5 pt-1 text-xs opacity-90">
          {report.failures.map((failure) => (
            <li key={failure.path} className="break-words">
              <code className="text-[0.7rem]">{failure.path}</code> — {failure.error}
            </li>
          ))}
        </ul>
      )}

      {report.below_min_tracks + report.unreadable + report.failed > 0 && (
        <div className="text-xs opacity-80">{t('metadata.report.hint')}</div>
      )}
    </div>
  )
}

/** What the cover.jpg / folder.jpg pass changed on disk. */
function ArtworkReport({ report }: { report: ArtworkSyncReport }) {
  const { t } = useTranslation()

  const parts = [
    t('metadata.artworkReport.found', { count: report.folders, path: report.root }),
    t('metadata.artworkReport.already', { count: report.already }),
    t('metadata.artworkReport.copied', { count: report.copied }),
    t('metadata.artworkReport.extracted', { count: report.extracted }),
  ]
  if (report.without_art > 0) {
    parts.push(t('metadata.artworkReport.withoutArt', { count: report.without_art }))
  }
  if (report.failed > 0) {
    parts.push(t('metadata.artworkReport.failed', { count: report.failed }))
  }

  return (
    <div className="space-y-1">
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.artworkReport.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {parts.join(' · ')}
      </div>

      {report.failures.length > 0 && (
        <ul className="space-y-0.5 pt-1 text-xs opacity-90">
          {report.failures.map((failure) => (
            <li key={failure.path} className="break-words">
              <code className="text-[0.7rem]">{failure.path}</code> — {failure.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** What Jellyfin was missing, and how much of it we managed to fill in. */
function CoverRepairReport({ report }: { report: JellyfinCoverReport }) {
  const { t } = useTranslation()

  if (report.without_cover === 0) {
    return (
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.coversReport.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {t('metadata.coversReport.nothingMissing', { count: report.albums })}
      </div>
    )
  }

  const parts = [
    t('metadata.coversReport.missing', {
      count: report.without_cover,
      total: report.albums,
    }),
    t('metadata.coversReport.fixedByRefresh', { count: report.fixed_by_refresh }),
    t('metadata.coversReport.uploaded', { count: report.uploaded }),
  ]
  if (report.no_source > 0) {
    parts.push(t('metadata.coversReport.noSource', { count: report.no_source }))
  }
  if (report.failed > 0) {
    parts.push(t('metadata.coversReport.failed', { count: report.failed }))
  }

  return (
    <div className="space-y-1">
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.coversReport.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {parts.join(' · ')}
      </div>

      {report.failures.length > 0 && (
        <ul className="space-y-0.5 pt-1 text-xs opacity-90">
          {report.failures.map((failure) => (
            <li key={failure.path} className="break-words">
              <code className="text-[0.7rem]">{failure.path}</code> — {failure.error}
            </li>
          ))}
        </ul>
      )}

      {report.no_source > 0 && (
        <div className="text-xs opacity-80">{t('metadata.coversReport.hint')}</div>
      )}
    </div>
  )
}

/** What Jellyfin disagreed on, and how much of it we managed to correct. */
function AlignReport({ report }: { report: JellyfinMetadataReport }) {
  const { t } = useTranslation()

  if (report.stale === 0) {
    return (
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.alignReport.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {t('metadata.alignReport.nothingStale', { count: report.compared })}
      </div>
    )
  }

  const parts = [
    t('metadata.alignReport.stale', { count: report.stale, total: report.compared }),
    t('metadata.alignReport.fixedByRefresh', { count: report.fixed_by_refresh }),
    t('metadata.alignReport.written', {
      albums: report.albums_written,
      tracks: report.tracks_written,
    }),
  ]
  if (report.unreadable > 0) {
    parts.push(t('metadata.alignReport.unreadable', { count: report.unreadable }))
  }
  if (report.left > 0) {
    parts.push(t('metadata.alignReport.left', { count: report.left }))
  }
  if (report.refresh_ignored) {
    parts.push(t('metadata.alignReport.refreshIgnored'))
  }
  if (report.failed > 0) {
    parts.push(t('metadata.alignReport.failed', { count: report.failed }))
  }

  return (
    <div className="space-y-1">
      <div>
        {report.finished_at && (
          <span className="font-semibold">
            {t('metadata.alignReport.when', { when: relativeTime(report.finished_at) })}{' '}
          </span>
        )}
        {parts.join(' · ')}
      </div>

      {report.samples.length > 0 && (
        <ul className="space-y-0.5 pt-1 text-xs opacity-90">
          {report.samples.map((sample) => (
            <li key={sample.path} className="break-words">
              <code className="text-[0.7rem]">{sample.path}</code> — {sample.error}
            </li>
          ))}
        </ul>
      )}

      {report.failures.length > 0 && (
        <ul className="space-y-0.5 pt-1 text-xs opacity-90">
          {report.failures.map((failure) => (
            <li key={failure.path} className="break-words">
              <code className="text-[0.7rem]">{failure.path}</code> — {failure.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function AlbumRow({ album, onOpen }: { album: MetadataAlbum; onOpen: () => void }) {
  const { t } = useTranslation()
  const matched = Boolean(album.match_release_group_mbid || album.match_release_mbid)

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-ink-700/25 sm:px-4"
    >
      <AlbumCover url={album.cover_url} alt="" size={100} className="size-12 shrink-0 rounded-lg" />

      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-ink-100">
          {album.album_title || album.path.split(/[/\\]/).pop()}
        </div>
        <div className="truncate text-xs text-ink-400">
          {[
            album.album_artist || t('metadata.unknownArtist'),
            album.year || null,
            t('metadata.trackCount', { count: album.track_count }),
            album.formats.join('/').toUpperCase() || null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </div>
      </div>

      <div className="hidden shrink-0 flex-wrap justify-end gap-1.5 sm:flex">
        {matched && (
          <Chip tone="brand">
            <Sparkles className="size-3" />
            {t('metadata.matchReady')}
          </Chip>
        )}
        {album.issues.map((kind) => (
          <Chip key={kind} tone="warning">
            {t(`metadata.issue.${kind}`)}
          </Chip>
        ))}
      </div>
    </button>
  )
}
