import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, EyeOff, Fingerprint, FolderOpen, Link2, Search, Wand2, X } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '../lib/api'
import { formatClock } from '../lib/format'
import type {
  MetadataAlbumDetail,
  MetadataApplyResult,
  MetadataPlan,
  MetadataProposal,
} from '../lib/types'
import { AlbumCover } from './AlbumCard'
import { useToast } from './Toast'
import { Alert, Button, CenteredSpinner, Chip, Input, Spinner } from './ui'

/** Tag rows shown in the before/after simulation, in a stable order. */
const TAG_ORDER = [
  'title',
  'artist',
  'albumartist',
  'album',
  'date',
  'track',
  'disc',
  'genres',
  'release_mbid',
  'release_group_mbid',
  'recording_mbid',
] as const

/** Tags describing the release rather than one track. */
const ALBUM_TAG_ORDER = [
  'album',
  'albumartist',
  'date',
  'genres',
  'release_mbid',
  'release_group_mbid',
] as const

function tagText(value: unknown): string {
  if (value == null || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  return String(value)
}

/** What a file really holds for one tag, repeats included.
 *
 * The reader keeps the first value of each field, so a tag written twice looks
 * perfectly normal there; the repeats are carried separately.
 */
function readValues(
  source: Record<string, unknown>,
  repeated: Record<string, string[]> | undefined,
  key: string,
): string[] {
  const doubled = repeated?.[key]
  if (doubled && doubled.length > 1) return doubled
  const value = source[key]
  if (value == null || value === '') return []
  if (Array.isArray(value)) return value.map((item) => String(item))
  return [String(value)]
}

/** A tag value as read, spelled out the way Picard does it: "Dushi ; Dushi".
 *
 * Joining the values into one string, as a first version did, is exactly what
 * hid the anomaly: the repeat has to be visible.
 */
function TagValues({ values }: { values: string[] }) {
  if (!values.length) return <span className="text-ink-600">—</span>
  const doubled = new Set(values.map((value) => value.toLowerCase())).size < values.length
  return (
    <span className={doubled ? 'text-amber-200' : undefined}>
      {values.map((value, index) => (
        <span key={`${value}-${index}`}>
          {index > 0 && <span className="text-amber-400/70"> ; </span>}
          {value}
        </span>
      ))}
    </span>
  )
}

/** Every tag of one file, laid out like the tag pane of Picard. */
function FileTagTable({
  values,
  repeated,
}: {
  values: Record<string, unknown>
  repeated: Record<string, string[]>
}) {
  const { t } = useTranslation()
  const extra = Object.keys(repeated).filter(
    (key) => !TAG_ORDER.includes(key as (typeof TAG_ORDER)[number]),
  )

  return (
    <table className="w-full text-left text-xs">
      <thead className="text-ink-500">
        <tr>
          <th className="w-40 py-1 pr-2 font-medium">{t('metadata.col.tag')}</th>
          <th className="py-1 font-medium">{t('metadata.col.readValues')}</th>
        </tr>
      </thead>
      <tbody className="text-ink-300">
        {[...TAG_ORDER, ...extra].map((key) => (
          <tr key={key} className="border-t border-ink-700/30 align-top">
            <td className="py-1 pr-2 text-ink-500">{key}</td>
            <td className="py-1 break-words">
              <TagValues values={readValues(values, repeated, key)} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Whether the tags can be rewritten as is.
 *
 * A chosen match is the usual way in, but an album already carrying its
 * MusicBrainz identifier in its tags needs nothing more: that is the case of
 * the folders whose only problem is a value written twice.
 */
function canWrite(album: MetadataAlbumDetail): boolean {
  return Boolean(
    album.match_release_group_mbid ||
      album.match_release_mbid ||
      album.release_mbid ||
      album.release_group_mbid,
  )
}

/** Scores come from the matcher on a 0-100 scale. */
function scoreTone(score: number) {
  if (score >= 90) return 'success' as const
  if (score >= 70) return 'brand' as const
  return 'warning' as const
}

export function MetadataAlbumPanel({
  albumId,
  onClose,
}: {
  albumId: number
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { notify } = useToast()
  const queryClient = useQueryClient()

  const [proposals, setProposals] = useState<MetadataProposal[] | null>(null)
  const [override, setOverride] = useState('')
  const [reference, setReference] = useState('')
  const [plan, setPlan] = useState<MetadataPlan | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [openTrack, setOpenTrack] = useState<string | null>(null)

  useEffect(() => {
    setProposals(null)
    setOverride('')
    setReference('')
    setPlan(null)
    setExpanded(null)
    setOpenTrack(null)
  }, [albumId])

  const detail = useQuery({
    queryKey: ['metadata', 'album', albumId],
    queryFn: () => api<MetadataAlbumDetail>(`/metadata/albums/${albumId}`),
  })

  const refreshLists = () => {
    void queryClient.invalidateQueries({ queryKey: ['metadata', 'albums'] })
    void queryClient.invalidateQueries({ queryKey: ['metadata', 'summary'] })
  }

  const fail = (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')

  const search = useMutation({
    mutationFn: () =>
      api<MetadataProposal[]>(`/metadata/albums/${albumId}/search`, {
        method: 'POST',
        query: override.trim() ? { q: override.trim() } : undefined,
      }),
    onSuccess: (result) => {
      setProposals(result)
      if (!result.length) notify(t('metadata.noCandidate'), 'info')
    },
    onError: fail,
  })

  const fingerprint = useMutation({
    mutationFn: () =>
      api<MetadataProposal[]>(`/metadata/albums/${albumId}/fingerprint`, { method: 'POST' }),
    onSuccess: (result) => {
      setProposals(result)
      if (!result.length) notify(t('metadata.noCandidate'), 'info')
    },
    onError: fail,
  })

  const choose = useMutation({
    mutationFn: (payload: {
      release_group_mbid?: string
      release_mbid?: string
      reference?: string
    }) =>
      api<MetadataAlbumDetail>(`/metadata/albums/${albumId}/match`, {
        method: 'POST',
        body: payload,
      }),
    onSuccess: (result) => {
      queryClient.setQueryData(['metadata', 'album', albumId], result)
      setPlan(null)
      setReference('')
      refreshLists()
      notify(t('metadata.matchStored'), 'success')
    },
    onError: fail,
  })

  const preview = useMutation({
    mutationFn: () => api<MetadataPlan>(`/metadata/albums/${albumId}/plan`),
    onSuccess: setPlan,
    onError: fail,
  })

  const apply = useMutation({
    mutationFn: () =>
      api<MetadataApplyResult>(`/metadata/albums/${albumId}/apply`, { method: 'POST' }),
    onSuccess: (result) => {
      notify(t('metadata.applied', { count: result.written }), 'success')
      setPlan(null)
      void detail.refetch()
      refreshLists()
    },
    onError: fail,
  })

  const setState = useMutation({
    mutationFn: (state: 'open' | 'ignored' | 'resolved') =>
      api(`/metadata/albums/${albumId}/state`, { method: 'POST', query: { state } }),
    onSuccess: () => {
      void detail.refetch()
      refreshLists()
    },
    onError: fail,
  })

  if (detail.isLoading) return <CenteredSpinner label={t('common.loading')} />
  const album = detail.data
  if (!album) return <Alert tone="error">{t('errors.generic')}</Alert>

  const matched = Boolean(album.match_release_group_mbid || album.match_release_mbid)
  const writable = canWrite(album)
  const duplicates = Array.isArray(album.details.duplicate_of)
    ? (album.details.duplicate_of as string[])
    : []
  const missingTags = Array.isArray(album.details.missing_tags)
    ? (album.details.missing_tags as string[])
    : []
  const doubled = album.details.duplicated_tags
  // Album wide tags are the same in every file; the first readable one speaks
  // for the folder.
  const albumTags = album.tracks.find((track) => track.readable) ?? album.tracks[0]

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------------- header */}
      <div className="flex flex-wrap items-start gap-4">
        <AlbumCover
          url={album.cover_url}
          alt=""
          size={300}
          className="size-24 shrink-0 rounded-xl shadow-lg"
        />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg text-ink-100">
            {album.album_title || t('metadata.unknownAlbum')}
          </div>
          <div className="text-sm text-ink-300">
            {album.album_artist || t('metadata.unknownArtist')}
            {album.year ? ` · ${album.year}` : ''}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {album.formats.map((format) => (
              <Chip key={format} tone={format === 'flac' ? 'success' : 'muted'}>
                {format.toUpperCase()}
              </Chip>
            ))}
            <Chip>{t('metadata.trackCount', { count: album.track_count })}</Chip>
            {album.issues.map((issue) => (
              <Chip key={issue} tone="warning">
                {t(`metadata.issue.${issue}`)}
              </Chip>
            ))}
          </div>
          <div className="mt-2 flex items-start gap-1.5 text-xs text-ink-400">
            <FolderOpen className="mt-0.5 size-3.5 shrink-0" />
            <span className="break-all font-mono">{album.path}</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {album.state === 'open' ? (
            <Button
              size="sm"
              variant="ghost"
              loading={setState.isPending}
              onClick={() => setState.mutate('ignored')}
              title={t('metadata.ignoreHint')}
            >
              <EyeOff className="size-3.5" />
              {t('metadata.ignore')}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              loading={setState.isPending}
              onClick={() => setState.mutate('open')}
            >
              {t('metadata.reopen')}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose} aria-label={t('common.close')}>
            <X className="size-4" />
          </Button>
        </div>
      </div>

      {album.details.scan_error && (
        <Alert tone="error">
          {t('metadata.scanErrorOnAlbum')}{' '}
          <span className="break-words font-mono text-xs">{album.details.scan_error}</span>
        </Alert>
      )}

      {duplicates.length > 0 && (
        <Alert tone="warning">
          {t('metadata.duplicateOf')}
          <ul className="mt-1 space-y-0.5">
            {duplicates.map((other) => (
              <li key={other} className="break-all font-mono text-xs opacity-80">
                {other}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {/* ------------------------------------------------------- identification */}
      <section className="space-y-3 rounded-2xl border border-ink-600/40 bg-ink-850/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-display text-sm uppercase tracking-wide text-ink-300">
            {t('metadata.identify')}
          </h4>
          {matched && (
            <Chip tone={scoreTone(album.match_score)}>
              <Check className="size-3" />
              {album.match_artist} — {album.match_title}
              {album.match_year ? ` (${album.match_year})` : ''} ·{' '}
              {Math.round(album.match_score)}%
            </Chip>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Input
            value={override}
            onChange={(event) => setOverride(event.target.value)}
            placeholder={t('metadata.overridePlaceholder')}
            className="min-w-48 flex-1"
            onKeyDown={(event) => {
              if (event.key === 'Enter') search.mutate()
            }}
          />
          <Button variant="primary" loading={search.isPending} onClick={() => search.mutate()}>
            <Search className="size-4" />
            {t('metadata.searchMusicBrainz')}
          </Button>
          <Button
            loading={fingerprint.isPending}
            onClick={() => fingerprint.mutate()}
            title={t('metadata.fingerprintHint')}
          >
            <Fingerprint className="size-4" />
            {t('metadata.fingerprint')}
          </Button>
        </div>

        <div className="flex flex-wrap gap-2">
          <Input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder={t('metadata.referencePlaceholder')}
            className="min-w-48 flex-1 font-mono text-xs"
          />
          <Button
            loading={choose.isPending}
            disabled={!reference.trim()}
            onClick={() => choose.mutate({ reference: reference.trim() })}
          >
            <Link2 className="size-4" />
            {t('metadata.useReference')}
          </Button>
        </div>

        {proposals && proposals.length > 0 && (
          <ul className="space-y-1.5">
            {proposals.map((proposal) => {
              const chosen =
                proposal.release_group_mbid === album.match_release_group_mbid ||
                (proposal.release_mbid && proposal.release_mbid === album.match_release_mbid)
              return (
                <li key={`${proposal.release_group_mbid}-${proposal.release_mbid}`}>
                  <button
                    type="button"
                    disabled={choose.isPending}
                    onClick={() =>
                      choose.mutate({
                        release_group_mbid: proposal.release_group_mbid,
                        release_mbid: proposal.release_mbid,
                      })
                    }
                    className={clsx(
                      'flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors',
                      chosen
                        ? 'border-brand-500/50 bg-brand-600/15'
                        : 'border-ink-600/40 hover:border-brand-500/40 hover:bg-ink-700/30',
                    )}
                  >
                    <AlbumCover
                      url={proposal.cover_url}
                      alt=""
                      size={100}
                      className="size-10 shrink-0 rounded-md"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-ink-100">{proposal.title}</div>
                      <div className="truncate text-xs text-ink-400">
                        {[
                          proposal.artist,
                          proposal.year || null,
                          // A release group holds no tracks: the count only
                          // exists once an edition has been picked.
                          proposal.track_count
                            ? t('metadata.trackCount', { count: proposal.track_count })
                            : null,
                          proposal.source ? t(`metadata.source.${proposal.source}`) : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </div>
                    </div>
                    <Chip tone={scoreTone(proposal.score)}>{Math.round(proposal.score)}%</Chip>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* ------------------------------------------------------------ current tags */}
      <section className="space-y-3 rounded-2xl border border-ink-600/40 bg-ink-850/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-display text-sm uppercase tracking-wide text-ink-300">
            {t('metadata.currentTags')}
          </h4>
          {missingTags.length > 0 && (
            <span className="text-xs text-amber-200">
              {t('metadata.missingTags', { tags: missingTags.join(', ') })}
            </span>
          )}
        </div>

        {doubled && (
          <Alert tone="warning">
            {t('metadata.doubledNotice', { count: doubled.file_count })}
            {/* Named one by one: the field at fault is often a tag no column
                shows, and hunting for it across twenty tracks is no fun. */}
            <ul className="mt-1 space-y-0.5 text-xs opacity-90">
              {doubled.files.map((file) => (
                <li key={file.name} className="break-words">
                  <code className="text-[0.7rem]">{file.name}</code> —{' '}
                  {Object.keys(file.tags).join(', ')}
                </li>
              ))}
            </ul>
          </Alert>
        )}

        {/* What the release itself declares, read from its first readable file. */}
        {albumTags && (
          <div className="rounded-xl border border-ink-600/40 p-3">
            <div className="mb-1 text-[0.7rem] uppercase tracking-wide text-ink-500">
              {t('metadata.albumTags')}
            </div>
            <table className="w-full text-left text-xs">
              <tbody className="text-ink-300">
                {ALBUM_TAG_ORDER.map((key) => (
                  <tr key={key} className="align-top">
                    <td className="w-40 py-0.5 pr-2 text-ink-500">{key}</td>
                    <td className="py-0.5 break-words">
                      <TagValues values={readValues(albumTags, albumTags.repeated, key)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 pr-3 font-medium">#</th>
                <th className="py-1 pr-3 font-medium">{t('metadata.col.title')}</th>
                <th className="py-1 pr-3 font-medium">{t('metadata.col.artist')}</th>
                <th className="py-1 pr-3 font-medium">{t('metadata.col.mbid')}</th>
                <th className="py-1 font-medium">{t('metadata.col.duration')}</th>
              </tr>
            </thead>
            <tbody className="text-ink-300">
              {album.tracks.map((track) => {
                const open = openTrack === track.path
                const carries = Object.keys(track.repeated ?? {}).length > 0
                return (
                  <Fragment key={track.path}>
                    <tr
                      onClick={() => setOpenTrack(open ? null : track.path)}
                      className="cursor-pointer border-t border-ink-700/40 hover:bg-ink-700/25"
                    >
                      <td
                        className={clsx(
                          'py-1.5 pr-3 tabular-nums',
                          carries ? 'text-amber-300' : 'text-ink-500',
                        )}
                        title={carries ? Object.keys(track.repeated ?? {}).join(', ') : undefined}
                      >
                        {track.track ?? '—'}
                      </td>
                      <td className="py-1.5 pr-3">
                        {track.title || track.repeated?.title ? (
                          <TagValues values={readValues(track, track.repeated, 'title')} />
                        ) : (
                          <span className="text-ink-500">{track.name}</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">
                        <TagValues values={readValues(track, track.repeated, 'artist')} />
                      </td>
                      <td className="py-1.5 pr-3">
                        {track.release_group_mbid || track.release_mbid ? (
                          <Check className="size-3.5 text-emerald-400" />
                        ) : (
                          <X className="size-3.5 text-ink-600" />
                        )}
                      </td>
                      <td className="py-1.5 tabular-nums text-ink-500">
                        {track.duration ? formatClock(track.duration) : '—'}
                      </td>
                    </tr>
                    {open && (
                      <tr className="border-t border-ink-700/30 bg-ink-900/40">
                        <td colSpan={5} className="px-3 py-2">
                          <div className="mb-1 break-all font-mono text-[0.7rem] text-ink-500">
                            {track.name}
                          </div>
                          <FileTagTable values={track} repeated={track.repeated ?? {}} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="hint">{t('metadata.trackTagsHint')}</p>
      </section>

      {/* --------------------------------------------------------------- write */}
      <section className="space-y-3 rounded-2xl border border-ink-600/40 bg-ink-850/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-display text-sm uppercase tracking-wide text-ink-300">
            {t('metadata.write')}
          </h4>
          <div className="flex gap-2">
            <Button
              size="sm"
              loading={preview.isPending}
              disabled={!writable}
              onClick={() => preview.mutate()}
            >
              {t('metadata.simulate')}
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={apply.isPending}
              disabled={!writable}
              onClick={() => {
                if (!window.confirm(t('metadata.confirmApply'))) return
                apply.mutate()
              }}
            >
              <Wand2 className="size-3.5" />
              {t('metadata.apply')}
            </Button>
          </div>
        </div>

        {!writable && <p className="hint">{t('metadata.matchFirst')}</p>}
        {!matched && writable && <p className="hint">{t('metadata.writeFromTagMbid')}</p>}

        {plan && (
          <div className="space-y-2">
            <div className="text-sm text-ink-200">
              {plan.artist} — {plan.album}
              {plan.year ? ` (${plan.year})` : ''}
            </div>
            {plan.cover_source && (
              <p className="hint">
                {t('metadata.coverSource', { source: t(`metadata.cover.${plan.cover_source}`) })}
              </p>
            )}
            {plan.warnings.map((warning) => (
              <Alert key={warning} tone="warning">
                {warning}
              </Alert>
            ))}
            {plan.unmatched.length > 0 && (
              <Alert tone="warning">
                {t('metadata.unmatched', { count: plan.unmatched.length })}
                <span className="mt-1 block break-all font-mono text-[0.7rem] opacity-80">
                  {plan.unmatched.join(', ')}
                </span>
              </Alert>
            )}

            <ul className="space-y-1">
              {plan.files.map((file) => (
                <li key={file.path} className="rounded-xl border border-ink-600/40">
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === file.path ? null : file.path)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left"
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-300">
                      {file.name}
                    </span>
                    {file.changed.length ? (
                      <Chip tone="brand">
                        {t('metadata.changedCount', { count: file.changed.length })}
                      </Chip>
                    ) : (
                      <Chip tone="muted">{t('metadata.unchanged')}</Chip>
                    )}
                  </button>
                  {expanded === file.path && (
                    <div className="border-t border-ink-700/40 px-3 py-2">
                      <table className="w-full text-left text-xs">
                        <tbody>
                          {TAG_ORDER.filter(
                            (key) => key in file.before || key in file.after,
                          ).map((key) => {
                            const changed = file.changed.includes(key)
                            return (
                              <tr key={key} className="align-top">
                                <td className="w-36 py-1 pr-2 text-ink-500">{key}</td>
                                <td className="w-1/2 py-1 pr-2 text-ink-400 line-through decoration-ink-600">
                                  {changed && (
                                    <TagValues
                                      values={readValues(file.before, file.repeated, key)}
                                    />
                                  )}
                                </td>
                                <td
                                  className={clsx(
                                    'py-1',
                                    changed ? 'text-emerald-200' : 'text-ink-400',
                                  )}
                                >
                                  {tagText(file.after[key])}
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {(preview.isPending || apply.isPending) && !plan && <Spinner />}
      </section>
    </div>
  )
}
