import clsx from 'clsx'
import { Check, FolderUp, Link2, Search, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, apiUpload } from '../lib/api'
import type { LocalImportSession, MetadataProposal } from '../lib/types'
import { AlbumCover } from './AlbumCard'
import { Alert, Button, Chip, Input, Modal } from './ui'

const AUDIO_OR_IMAGE =
  /\.(flac|mp3|m4a|alac|aac|ogg|opus|wav|aiff|aif|ape|wv|wma|dsf|dff|mpc|shn|jpe?g|png|gif|bmp|webp|tiff?)$/i

const BATCH = 6

type Staged = { file: File; relative: string }

type Step = 'closed' | 'upload' | 'identify' | 'manual' | 'done'

function isKept(name: string): boolean {
  return AUDIO_OR_IMAGE.test(name)
}

function readDirectory(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const collected: FileSystemEntry[] = []
    const pump = () => {
      reader.readEntries(
        (batch) => {
          if (!batch.length) {
            resolve(collected)
            return
          }
          collected.push(...batch)
          pump()
        },
        reject,
      )
    }
    pump()
  })
}

function readFileEntry(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function walkEntry(entry: FileSystemEntry, prefix = ''): Promise<Staged[]> {
  const relative = prefix ? `${prefix}/${entry.name}` : entry.name
  if (entry.isFile) {
    if (!isKept(entry.name)) return []
    const file = await readFileEntry(entry as FileSystemFileEntry)
    return [{ file, relative }]
  }
  if (!entry.isDirectory) return []
  const children = await readDirectory((entry as FileSystemDirectoryEntry).createReader())
  const staged: Staged[] = []
  for (const child of children) {
    staged.push(...(await walkEntry(child, relative)))
  }
  return staged
}

async function fromDataTransfer(transfer: DataTransfer): Promise<Staged[]> {
  const items = [...transfer.items]
  const entries = items
    .map((item) => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => Boolean(entry))
  if (entries.length) {
    const staged: Staged[] = []
    for (const entry of entries) {
      staged.push(...(await walkEntry(entry)))
    }
    return staged
  }
  return [...transfer.files]
    .filter((file) => isKept(file.name))
    .map((file) => ({
      file,
      relative: file.webkitRelativePath || file.name,
    }))
}

function fromFileList(list: FileList | null): Staged[] {
  if (!list) return []
  return [...list]
    .filter((file) => isKept(file.name))
    .map((file) => ({
      file,
      relative: file.webkitRelativePath || file.name,
    }))
}

export function LocalImportCard() {
  const { t } = useTranslation()
  const folderInput = useRef<HTMLInputElement>(null)
  const coverInput = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [step, setStep] = useState<Step>('closed')
  const [session, setSession] = useState<LocalImportSession | null>(null)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [reference, setReference] = useState('')
  const [artist, setArtist] = useState('')
  const [album, setAlbum] = useState('')
  const [year, setYear] = useState('')
  const [busy, setBusy] = useState(false)

  function apply(next: LocalImportSession) {
    setSession(next)
    setArtist(next.artist)
    setAlbum(next.album)
    setYear(next.year)
  }

  async function abort(id?: string) {
    const target = id || session?.id
    if (target) {
      await api(`/local-import/sessions/${target}`, { method: 'DELETE' }).catch(() => undefined)
    }
  }

  async function close() {
    if (session && session.status !== 'committed') {
      await abort(session.id)
    }
    setSession(null)
    setStep('closed')
    setError('')
    setProgress('')
    setQuery('')
    setReference('')
  }

  async function start(items: Staged[]) {
    const audio = items.filter((item) => !/\.(jpe?g|png|gif|bmp|webp|tiff?)$/i.test(item.relative))
    if (!audio.length) {
      setError(t('importLocal.files', { count: 0 }))
      return
    }
    setError('')
    setStep('upload')
    setBusy(true)
    let created: LocalImportSession | null = null
    try {
      created = await api<LocalImportSession>('/local-import/sessions', { method: 'POST' })
      setSession(created)
      for (let index = 0; index < items.length; index += BATCH) {
        const batch = items.slice(index, index + BATCH)
        const form = new FormData()
        for (const item of batch) {
          form.append('files', item.file)
          form.append('paths', item.relative)
        }
        await apiUpload(`/local-import/sessions/${created.id}/files`, form)
        setProgress(`${Math.min(index + BATCH, items.length)} / ${items.length}`)
      }
      setProgress(t('importLocal.analyzing'))
      const analysed = await api<LocalImportSession>(
        `/local-import/sessions/${created.id}/analyze`,
        { method: 'POST', body: { query: '' } },
      )
      apply(analysed)
      setStep('identify')
    } catch (cause) {
      if (created) await abort(created.id)
      setSession(null)
      setStep('closed')
      setError(cause instanceof Error ? cause.message : t('errors.generic'))
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
    setBusy(true)
    setError('')
    try {
      return await work()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('errors.generic'))
      return undefined
    } finally {
      setBusy(false)
    }
  }

  async function search() {
    if (!session) return
    const next = await run(() =>
      api<LocalImportSession>(`/local-import/sessions/${session.id}/search`, {
        method: 'POST',
        body: { query },
      }),
    )
    if (next) apply(next)
  }

  async function choose(proposal: MetadataProposal) {
    if (!session) return
    const next = await run(() =>
      api<LocalImportSession>(`/local-import/sessions/${session.id}/match`, {
        method: 'POST',
        body: {
          release_group_mbid: proposal.release_group_mbid,
          release_mbid: proposal.release_mbid,
        },
      }),
    )
    if (next) apply(next)
  }

  async function useReference() {
    if (!session || !reference.trim()) return
    const next = await run(() =>
      api<LocalImportSession>(`/local-import/sessions/${session.id}/match`, {
        method: 'POST',
        body: { reference: reference.trim() },
      }),
    )
    if (next) apply(next)
  }

  async function saveManual(): Promise<LocalImportSession | undefined> {
    if (!session) return
    const next = await run(() =>
      api<LocalImportSession>(`/local-import/sessions/${session.id}/manual`, {
        method: 'POST',
        body: { artist, album, year },
      }),
    )
    if (next) apply(next)
    return next
  }

  async function uploadCover(file: File) {
    if (!session) return
    const form = new FormData()
    form.append('file', file)
    const next = await run(() =>
      apiUpload<LocalImportSession>(`/local-import/sessions/${session.id}/cover`, form),
    )
    if (next) apply(next)
  }

  async function commit(confirmUpgrade = false) {
    if (!session) return
    if (step === 'manual') {
      const stored = await saveManual()
      if (!stored) return
    }
    const next = await run(() =>
      api<LocalImportSession>(`/local-import/sessions/${session.id}/commit`, {
        method: 'POST',
        body: { confirm_upgrade: confirmUpgrade },
      }),
    )
    if (next) {
      apply(next)
      setStep('done')
    }
  }

  const identified = session?.status === 'identified'
  const blocked = Boolean(session?.ownership?.blocked)
  const upgradable = Boolean(session?.ownership?.upgradable)
  const canWrite =
    identified && !blocked && Boolean(session?.has_cover) && Boolean(session?.artist) && Boolean(session?.album)

  return (
    <>
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          void fromDataTransfer(event.dataTransfer).then(start)
        }}
        className={clsx(
          'flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed px-6 py-12 text-center transition-colors',
          over ? 'border-brand-400 bg-brand-600/10' : 'border-ink-600/60',
        )}
      >
        <FolderUp className="size-10 text-ink-500" />
        <div className="font-display text-lg text-ink-200">{t('importLocal.title')}</div>
        <p className="max-w-lg text-sm text-ink-400">{t('importLocal.hint')}</p>
        <p className="text-sm text-ink-500">{t('importLocal.drop')}</p>
        <Button variant="primary" onClick={() => folderInput.current?.click()}>
          <Upload className="size-4" />
          {t('importLocal.browse')}
        </Button>
        {error && step === 'closed' && (
          <p className="max-w-lg text-sm text-accent-300">{error}</p>
        )}
        <input
          ref={folderInput}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => {
            const items = fromFileList(event.target.files)
            event.target.value = ''
            void start(items)
          }}
          {...{ webkitdirectory: '', directory: '' }}
        />
      </div>

      <Modal
        open={step !== 'closed'}
        onClose={() => {
          if (!busy) void close()
        }}
        title={
          step === 'done'
            ? t('importLocal.done')
            : step === 'manual'
              ? t('importLocal.manualTitle')
              : t('importLocal.identify')
        }
        wide
        footer={
          step === 'done' ? (
            <Button variant="primary" onClick={() => void close()}>
              {t('importLocal.close')}
            </Button>
          ) : step === 'manual' ? (
            <>
              <Button onClick={() => setStep('identify')} disabled={busy}>
                {t('common.back')}
              </Button>
              <Button
                variant="primary"
                loading={busy}
                disabled={!artist.trim() || !album.trim() || !session?.has_cover || blocked}
                onClick={() => void commit(upgradable)}
              >
                {upgradable ? t('importLocal.confirmUpgrade') : t('importLocal.write')}
              </Button>
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setStep('manual')} disabled={busy || !session}>
                {t('importLocal.notOnMusicBrainz')}
              </Button>
              <Button
                variant="primary"
                loading={busy}
                disabled={!canWrite}
                onClick={() => void commit(upgradable)}
              >
                {upgradable ? t('importLocal.confirmUpgrade') : t('importLocal.write')}
              </Button>
            </>
          )
        }
      >
        {progress && <p className="mb-3 text-sm text-ink-400">{progress}</p>}
        {error && step !== 'closed' && (
          <Alert tone="error" className="mb-3">
            {error}
          </Alert>
        )}

        {session && step !== 'done' && (
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-300">
            <Chip>{t('importLocal.files', { count: session.track_count })}</Chip>
            <Chip tone={session.is_lossless ? 'brand' : 'muted'}>
              {session.is_lossless ? t('importLocal.lossless') : t('importLocal.lossy')}
            </Chip>
            {session.artist && session.album && (
              <span className="truncate">
                {session.artist} — {session.album}
                {session.year ? ` (${session.year})` : ''}
              </span>
            )}
          </div>
        )}

        {session?.ownership?.blocked && (
          <Alert tone="warning" className="mb-3">
            {t('importLocal.ownedBlocked')}
          </Alert>
        )}
        {session?.ownership?.upgradable && (
          <Alert tone="info" className="mb-3">
            {t('importLocal.upgradeOffer')}
          </Alert>
        )}

        {step === 'identify' && session && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('importLocal.searchPlaceholder')}
                className="min-w-48 flex-1"
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void search()
                }}
              />
              <Button variant="primary" loading={busy} onClick={() => void search()}>
                <Search className="size-4" />
                {t('importLocal.searchMusicBrainz')}
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              <Input
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                placeholder={t('importLocal.referencePlaceholder')}
                className="min-w-48 flex-1 font-mono text-xs"
              />
              <Button loading={busy} disabled={!reference.trim()} onClick={() => void useReference()}>
                <Link2 className="size-4" />
                {t('importLocal.useReference')}
              </Button>
            </div>

            {session.mode === 'musicbrainz' && session.release_mbid && (
              <Chip tone="brand">
                <Check className="size-3" />
                {t('importLocal.chosen')} · {session.artist} — {session.album}
              </Chip>
            )}

            {session.proposals.length === 0 ? (
              <p className="text-sm text-ink-400">{t('importLocal.noCandidate')}</p>
            ) : (
              <ul className="space-y-1.5">
                {session.proposals.map((proposal) => {
                  const chosen =
                    proposal.release_group_mbid === session.release_group_mbid &&
                    (!proposal.release_mbid || proposal.release_mbid === session.release_mbid)
                  return (
                    <li key={`${proposal.release_group_mbid}-${proposal.release_mbid}`}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void choose(proposal)}
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
                            {[proposal.artist, proposal.year || null, proposal.source]
                              .filter(Boolean)
                              .join(' · ')}
                          </div>
                        </div>
                        <span className="text-xs text-ink-500">{Math.round(proposal.score)}%</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )}

        {step === 'manual' && session && (
          <div className="space-y-4">
            <p className="text-sm text-ink-400">{t('importLocal.manualHint')}</p>
            <div className="grid gap-3 sm:grid-cols-[7rem_1fr]">
              <div>
                <div className="label">{t('importLocal.cover')}</div>
                <button
                  type="button"
                  className="block overflow-hidden rounded-xl border border-ink-600/40"
                  onClick={() => coverInput.current?.click()}
                >
                  <AlbumCover
                    url={session.cover_url}
                    alt=""
                    size={200}
                    className="size-28"
                  />
                </button>
                <Button
                  size="sm"
                  className="mt-2"
                  onClick={() => coverInput.current?.click()}
                >
                  {t('importLocal.changeCover')}
                </Button>
                {!session.has_cover && (
                  <p className="mt-1 text-xs text-accent-300">{t('importLocal.missingCover')}</p>
                )}
                <input
                  ref={coverInput}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    event.target.value = ''
                    if (file) void uploadCover(file)
                  }}
                />
              </div>
              <div className="space-y-3">
                <label className="block">
                  <span className="label">{t('importLocal.artist')}</span>
                  <Input value={artist} onChange={(event) => setArtist(event.target.value)} />
                </label>
                <label className="block">
                  <span className="label">{t('importLocal.album')}</span>
                  <Input value={album} onChange={(event) => setAlbum(event.target.value)} />
                </label>
                <label className="block">
                  <span className="label">{t('importLocal.year')}</span>
                  <Input value={year} onChange={(event) => setYear(event.target.value)} />
                </label>
              </div>
            </div>
          </div>
        )}

        {step === 'done' && session && (
          <div className="space-y-2 text-sm text-ink-300">
            <p>
              {session.artist} — {session.album}
            </p>
            {session.destination && (
              <p className="break-all font-mono text-xs text-ink-400">
                {t('importLocal.destination')} · {session.destination}
              </p>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}
