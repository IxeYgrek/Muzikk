import clsx from 'clsx'
import {
  ListMusic,
  ListPlus,
  Pause,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { formatClock } from '../lib/format'
import { usePlayer } from '../lib/player'
import { AddToPlaylistModal, type PlaylistTarget } from './AddToPlaylist'
import { AlbumCover } from './AlbumCard'
import { Spinner } from './ui'

/** Persistent bar at the bottom of the screen, shown once something plays. */
export function Player() {
  const { t } = useTranslation()
  const player = usePlayer()
  const [showQueue, setShowQueue] = useState(false)
  const [playlistTarget, setPlaylistTarget] = useState<PlaylistTarget | null>(null)

  const {
    current,
    queue,
    index,
    playing,
    loading,
    position,
    duration,
    volume,
    muted,
    shuffle,
    repeat,
    error,
  } = player

  if (!current) return null

  const length = duration || current.duration || 0

  return (
    <>
      {showQueue && (
        <div className="fixed inset-0 z-40 lg:pl-64" onClick={() => setShowQueue(false)} role="presentation">
          <div className="absolute inset-x-0 bottom-[5.5rem] mx-auto max-h-[60vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-ink-600/50 bg-ink-900/95 p-2 shadow-2xl backdrop-blur-xl sm:bottom-24 sm:px-3">
            <div className="px-2 py-2 text-xs font-semibold uppercase tracking-wide text-ink-400">
              {t('player.queue', { count: queue.length })}
            </div>
            {queue.map((track, position_) => (
              <button
                key={`${track.jellyfin_id}-${position_}`}
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  player.jumpTo(position_)
                }}
                className={clsx(
                  'flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left text-sm transition-colors',
                  position_ === index
                    ? 'bg-brand-600/20 text-ink-50'
                    : 'text-ink-300 hover:bg-ink-700/40',
                )}
              >
                <span className="w-6 shrink-0 text-right text-xs tabular-nums text-ink-500">
                  {track.track ?? position_ + 1}
                </span>
                <span className="min-w-0 flex-1 truncate">{track.title}</span>
                <span className="hidden shrink-0 truncate text-xs text-ink-500 sm:block">
                  {track.artist}
                </span>
                <span className="shrink-0 text-xs tabular-nums text-ink-500">
                  {track.duration ? formatClock(track.duration) : ''}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-ink-700/60 bg-ink-900/95 backdrop-blur-xl lg:pl-64">
        {/* Full width seek bar. Its control area covers the top edge of the
            player so a click aimed slightly high lands here, not on the page
            behind; the line it draws is the bottom of that area. */}
        <input
          type="range"
          min={0}
          max={Math.max(1, Math.floor(length))}
          value={Math.floor(position)}
          onChange={(event) => player.seek(Number(event.target.value))}
          aria-label={t('player.seek')}
          className="player-seek"
          style={{ '--played': `${length ? (position / length) * 100 : 0}%` } as CSSProperties}
        />

        <div className="mx-auto flex w-full max-w-[100rem] items-center gap-3 px-3 pb-2.5 sm:gap-4 sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <AlbumCover
              url={current.cover_url}
              alt=""
              size={120}
              className="size-11 shrink-0 rounded-lg shadow-lg"
            />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-ink-100">{current.title}</span>
                {current.preview && (
                  <span
                    className="shrink-0 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[0.65rem] font-semibold text-amber-200"
                    title={t('player.previewFrom', { source: current.preview })}
                  >
                    {t('player.preview')}
                  </span>
                )}
              </div>
              <div className="truncate text-xs text-ink-400">
                {error ? (
                  <span className="text-accent-300" title={error}>
                    {t('player.unplayable')}
                    {error !== current.title ? ` · ${error}` : ''}
                  </span>
                ) : (
                  [current.artist, current.album].filter(Boolean).join(' · ')
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={player.previous}
              className="rounded-lg p-2 text-ink-300 transition-colors hover:bg-ink-700/50 hover:text-ink-100"
              aria-label={t('player.previous')}
            >
              <SkipBack className="size-4" />
            </button>
            <button
              type="button"
              onClick={player.toggle}
              className="grid size-10 place-items-center rounded-full gradient-surface text-white shadow-lg transition-transform hover:scale-105"
              aria-label={playing ? t('player.pause') : t('player.play')}
            >
              {loading ? (
                <Spinner className="size-4 text-white" />
              ) : playing ? (
                <Pause className="size-4" />
              ) : (
                <Play className="size-4" />
              )}
            </button>
            <button
              type="button"
              onClick={player.next}
              className="rounded-lg p-2 text-ink-300 transition-colors hover:bg-ink-700/50 hover:text-ink-100"
              aria-label={t('player.next')}
            >
              <SkipForward className="size-4" />
            </button>
          </div>

          <div className="hidden shrink-0 items-center gap-3 text-xs tabular-nums text-ink-400 sm:flex">
            {formatClock(position)} / {formatClock(length)}
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            {current.jellyfin_id && (
              <button
                type="button"
                onClick={() =>
                  setPlaylistTarget({
                    label: [current.artist, current.title].filter(Boolean).join(' — '),
                    trackIds: [current.jellyfin_id],
                  })
                }
                title={t('playlists.addTo')}
                aria-label={t('playlists.addTo')}
                className="rounded-lg p-2 text-ink-400 transition-colors hover:bg-ink-700/50 hover:text-ink-100"
              >
                <ListPlus className="size-4" />
              </button>
            )}
            <button
              type="button"
              onClick={player.toggleShuffle}
              title={t('player.shuffle')}
              className={clsx(
                'rounded-lg p-2 transition-colors hover:bg-ink-700/50',
                shuffle ? 'text-brand-300' : 'text-ink-400 hover:text-ink-100',
              )}
            >
              <Shuffle className="size-4" />
            </button>
            <button
              type="button"
              onClick={player.cycleRepeat}
              title={t(`player.repeat.${repeat}`)}
              className={clsx(
                'rounded-lg p-2 transition-colors hover:bg-ink-700/50',
                repeat === 'off' ? 'text-ink-400 hover:text-ink-100' : 'text-brand-300',
              )}
            >
              {repeat === 'one' ? <Repeat1 className="size-4" /> : <Repeat className="size-4" />}
            </button>
            <button
              type="button"
              onClick={() => setShowQueue((value) => !value)}
              title={t('player.queueTitle')}
              className={clsx(
                'rounded-lg p-2 transition-colors hover:bg-ink-700/50',
                showQueue ? 'text-brand-300' : 'text-ink-400 hover:text-ink-100',
              )}
            >
              <ListMusic className="size-4" />
            </button>

            <div className="hidden items-center gap-1.5 pl-1 md:flex">
              <button
                type="button"
                onClick={player.toggleMute}
                className="rounded-lg p-2 text-ink-400 transition-colors hover:bg-ink-700/50 hover:text-ink-100"
                aria-label={t('player.mute')}
              >
                {muted || volume === 0 ? (
                  <VolumeX className="size-4" />
                ) : (
                  <Volume2 className="size-4" />
                )}
              </button>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((muted ? 0 : volume) * 100)}
                onChange={(event) => player.setVolume(Number(event.target.value) / 100)}
                aria-label={t('player.volume')}
                className="player-volume"
              />
            </div>

            <button
              type="button"
              onClick={player.stop}
              className="rounded-lg p-2 text-ink-400 transition-colors hover:bg-ink-700/50 hover:text-accent-300"
              aria-label={t('player.close')}
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      </div>

      {playlistTarget && (
        <AddToPlaylistModal target={playlistTarget} onClose={() => setPlaylistTarget(null)} />
      )}
    </>
  )
}
