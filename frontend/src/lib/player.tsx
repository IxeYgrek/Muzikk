import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'

import { api, imageUrl, probeMedia, streamUrl } from './api'
import type { PlayableTrack } from './types'

export type RepeatMode = 'off' | 'all' | 'one'

type PlayerState = {
  queue: PlayableTrack[]
  index: number
  current: PlayableTrack | null
  playing: boolean
  loading: boolean
  position: number
  duration: number
  volume: number
  muted: boolean
  shuffle: boolean
  repeat: RepeatMode
  error: string | null
}

type PlayerContextValue = PlayerState & {
  playAlbum: (albumId: string, startAt?: number | string) => Promise<void>
  playTracks: (tracks: PlayableTrack[], startAt?: number) => void
  enqueue: (tracks: PlayableTrack[]) => void
  toggle: () => void
  next: () => void
  previous: () => void
  jumpTo: (index: number) => void
  seek: (seconds: number) => void
  setVolume: (value: number) => void
  toggleMute: () => void
  toggleShuffle: () => void
  cycleRepeat: () => void
  stop: () => void
}

const PlayerContext = createContext<PlayerContextValue | null>(null)

const VOLUME_KEY = 'muzikk.volume'
// Jellyfin only needs a heartbeat, not every timeupdate event.
const REPORT_INTERVAL_MS = 20_000

/**
 * What tells two queue entries apart.
 *
 * A library track is its Jellyfin identifier. A thirty second extract has
 * none, so its stream URL — which carries the artist and the title — stands in.
 */
function trackKey(track: PlayableTrack | null): string {
  if (!track) return ''
  return track.jellyfin_id || track.stream_url
}

function readVolume(): number {
  try {
    const stored = Number(window.localStorage.getItem(VOLUME_KEY))
    return Number.isFinite(stored) && stored > 0 && stored <= 1 ? stored : 0.9
  } catch {
    return 0.9
  }
}

/** Fisher-Yates on the upcoming tracks only: the current one keeps playing. */
function shuffleRest(tracks: PlayableTrack[], from: number): PlayableTrack[] {
  const head = tracks.slice(0, from + 1)
  const tail = tracks.slice(from + 1)
  for (let index = tail.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1))
    ;[tail[index], tail[swap]] = [tail[swap], tail[index]]
  }
  return [...head, ...tail]
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const reportedAt = useRef(0)
  const reportedTrack = useRef<string | null>(null)
  const loadedKey = useRef('')
  // A transcoded stream has no byte index, so a seek restarts ffmpeg at this
  // offset and the displayed position is offset + currentTime.
  const transcodeOffset = useRef(0)

  const [queue, setQueue] = useState<PlayableTrack[]>([])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolumeState] = useState(readVolume)
  const [muted, setMuted] = useState(false)
  const [shuffle, setShuffle] = useState(false)
  const [repeat, setRepeat] = useState<RepeatMode>('off')
  const [error, setError] = useState<string | null>(null)

  const current = queue[index] ?? null

  if (audioRef.current === null && typeof Audio !== 'undefined') {
    audioRef.current = new Audio()
    audioRef.current.preload = 'metadata'
  }

  const report = useCallback((stage: 'start' | 'progress' | 'stop', track: PlayableTrack | null) => {
    // An extract is not a listen: there is no library item to credit it to.
    if (!track || !track.jellyfin_id) return
    const audio = audioRef.current
    void api('/play/report', {
      method: 'POST',
      query: {
        item_id: track.jellyfin_id,
        stage,
        position_ms: Math.round((audio?.currentTime ?? 0) * 1000),
        paused: stage === 'progress' ? Boolean(audio?.paused) : false,
      },
    }).catch(() => undefined)
  }, [])

  // Loading a new source: the audio element is reused across tracks so the
  // browser keeps the same media session.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (!current) {
      loadedKey.current = ''
      audio.removeAttribute('src')
      audio.load()
      return
    }

    // Compared on the key rather than on the URL: a token refreshed between
    // two renders changes the source without changing the track, and two
    // extracts share the same path with a different query string.
    const key = trackKey(current)
    if (loadedKey.current === key) return
    loadedKey.current = key

    if (reportedTrack.current && reportedTrack.current !== current.jellyfin_id) {
      report('stop', queue.find((item) => item.jellyfin_id === reportedTrack.current) ?? null)
    }

    if (current.playable === false) {
      transcodeOffset.current = 0
      audio.removeAttribute('src')
      audio.load()
      setLoading(false)
      setPlaying(false)
      setPosition(0)
      setDuration(current.duration ?? 0)
      setError(current.title)
      return
    }

    setError(null)
    setLoading(true)
    transcodeOffset.current = 0
    setPosition(0)
    setDuration(current.duration ?? 0)
    audio.src = streamUrl(current.stream_url)
    audio.load()
    void audio
      .play()
      .then(() => {
        reportedTrack.current = current.jellyfin_id
        reportedAt.current = Date.now()
        report('start', current)
      })
      .catch(() => {
        // Autoplay refused, or an unplayable file: stay on the track, paused.
        setPlaying(false)
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackKey(current)])

  useEffect(() => {
    const audio = audioRef.current
    if (audio) {
      audio.volume = volume
      audio.muted = muted
    }
    try {
      window.localStorage.setItem(VOLUME_KEY, String(volume))
    } catch {
      /* private browsing */
    }
  }, [volume, muted])

  const advance = useCallback(
    (direction: 1 | -1) => {
      setIndex((position_) => {
        const target = position_ + direction
        if (target >= queue.length) return repeat === 'all' ? 0 : position_
        if (target < 0) return 0
        return target
      })
    },
    [queue.length, repeat],
  )

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const onPlay = () => {
      setPlaying(true)
      setLoading(false)
    }
    // 'play' only fires when playback is asked for. Coming back from a stall
    // fires 'playing' alone, and that is what tells the spinner to stop.
    const onPlaying = () => {
      setPlaying(true)
      setLoading(false)
    }
    // Enough data to resume, even while paused: nothing is being waited on.
    const onCanPlay = () => setLoading(false)
    const onPause = () => setPlaying(false)
    const onTime = () => {
      const track = queue[index] ?? null
      const elapsed = track?.transcoded
        ? transcodeOffset.current + audio.currentTime
        : audio.currentTime
      setPosition(elapsed)
      // Sound is coming out, whatever the events said: nothing is loading.
      if (!audio.paused) setLoading(false)
      if (Date.now() - reportedAt.current > REPORT_INTERVAL_MS) {
        reportedAt.current = Date.now()
        report('progress', track)
      }
    }
    const onMeta = () => {
      const track = queue[index] ?? null
      // A re-encoded pipe has no known length; keep the tag duration.
      if (!track?.transcoded && Number.isFinite(audio.duration)) {
        setDuration(audio.duration)
      }
      setLoading(false)
    }
    const onEnded = () => {
      report('stop', queue[index] ?? null)
      const last = index >= queue.length - 1
      // Looping a single track, or a one-track queue, keeps the same source:
      // the loading effect would not fire, so rewind by hand.
      if (repeat === 'one' || (repeat === 'all' && queue.length === 1)) {
        audio.currentTime = 0
        void audio.play()
        return
      }
      if (last && repeat !== 'all') {
        setPlaying(false)
        return
      }
      advance(1)
    }
    const onError = () => {
      setLoading(false)
      setPlaying(false)
      const track = queue[index] ?? null
      setError(track?.title ?? 'error')
      // The event says nothing useful: ask the server what went wrong.
      if (track) {
        void probeMedia(track.stream_url).then((detail) => {
          if (detail) setError(detail)
        })
      }
    }
    const onWaiting = () => setLoading(true)

    audio.addEventListener('play', onPlay)
    audio.addEventListener('playing', onPlaying)
    audio.addEventListener('canplay', onCanPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('loadedmetadata', onMeta)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('error', onError)
    audio.addEventListener('waiting', onWaiting)
    return () => {
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('playing', onPlaying)
      audio.removeEventListener('canplay', onCanPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('loadedmetadata', onMeta)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
      audio.removeEventListener('waiting', onWaiting)
    }
  }, [advance, index, queue, repeat, report])

  // Let the operating system media keys drive the player.
  useEffect(() => {
    if (!('mediaSession' in navigator) || !current) return
    const artwork = imageUrl(current.cover_url, 512)
    navigator.mediaSession.metadata = new MediaMetadata({
      title: current.title,
      artist: current.artist,
      album: current.album,
      artwork: artwork ? [{ src: artwork }] : undefined,
    })
    navigator.mediaSession.setActionHandler('previoustrack', () => advance(-1))
    navigator.mediaSession.setActionHandler('nexttrack', () => advance(1))
  }, [advance, current])

  const playTracks = useCallback(
    (tracks: PlayableTrack[], startAt = 0) => {
      if (!tracks.length) return
      const target = Math.max(0, Math.min(startAt, tracks.length - 1))
      const again = trackKey(queue[index] ?? null) === trackKey(tracks[target] ?? null)
      setQueue(tracks)
      setIndex(target)
      // Asking again for the track already loaded keeps the same source, so the
      // loading effect stays quiet: restart it by hand.
      const audio = audioRef.current
      if (again && audio) {
        const same = tracks[target]
        if (same?.transcoded) {
          transcodeOffset.current = 0
          audio.src = streamUrl(same.stream_url)
          audio.load()
        } else {
          audio.currentTime = 0
        }
        void audio.play().catch(() => setPlaying(false))
      }
    },
    [index, queue],
  )

  const playAlbum = useCallback(
    async (albumId: string, startAt: number | string = 0) => {
      setLoading(true)
      try {
        const tracks = await api<PlayableTrack[]>(`/play/album/${albumId}`)
        // A track identifier is accepted too, so a search hit can start on it.
        const position_ =
          typeof startAt === 'string'
            ? Math.max(
                0,
                tracks.findIndex((track) => track.jellyfin_id === startAt),
              )
            : startAt
        playTracks(tracks, position_)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'error')
      } finally {
        setLoading(false)
      }
    },
    [playTracks],
  )

  const enqueue = useCallback((tracks: PlayableTrack[]) => {
    setQueue((existing) => [...existing, ...tracks])
  }, [])

  const toggle = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !current) return
    if (audio.paused) {
      void audio.play().catch(() => setPlaying(false))
    } else {
      audio.pause()
      report('progress', current)
    }
  }, [current, report])

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current
    if (!audio) return
    const track = queue[index] ?? null
    const target = Math.max(0, seconds)
    if (track?.transcoded) {
      transcodeOffset.current = target
      setPosition(target)
      setLoading(true)
      audio.src = streamUrl(track.stream_url, { start: target.toFixed(3) })
      audio.load()
      void audio.play().catch(() => {
        setPlaying(false)
        setLoading(false)
      })
      return
    }
    audio.currentTime = target
    setPosition(audio.currentTime)
  }, [index, queue])

  const previous = useCallback(() => {
    const audio = audioRef.current
    const elapsed = transcodeOffset.current + (audio?.currentTime ?? 0)
    // Restart the track first, like every other player does.
    if (audio && elapsed > 3) {
      seek(0)
      return
    }
    advance(-1)
  }, [advance, seek])

  const toggleShuffle = useCallback(() => {
    setShuffle((value) => {
      const next_ = !value
      if (next_) setQueue((tracks) => shuffleRest(tracks, index))
      return next_
    })
  }, [index])

  const stop = useCallback(() => {
    const audio = audioRef.current
    report('stop', queue[index] ?? null)
    if (audio) {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    }
    reportedTrack.current = null
    loadedKey.current = ''
    setQueue([])
    setIndex(0)
    setPlaying(false)
    setPosition(0)
    setDuration(0)
  }, [index, queue, report])

  const value = useMemo<PlayerContextValue>(
    () => ({
      queue,
      index,
      current,
      playing,
      loading,
      position,
      duration,
      volume,
      muted,
      shuffle,
      repeat,
      error,
      playAlbum,
      playTracks,
      enqueue,
      toggle,
      next: () => advance(1),
      previous,
      jumpTo: (target: number) => setIndex(Math.max(0, Math.min(target, queue.length - 1))),
      seek,
      setVolume: setVolumeState,
      toggleMute: () => setMuted((state) => !state),
      toggleShuffle,
      cycleRepeat: () =>
        setRepeat((mode) => (mode === 'off' ? 'all' : mode === 'all' ? 'one' : 'off')),
      stop,
    }),
    [
      advance,
      current,
      duration,
      enqueue,
      error,
      index,
      loading,
      muted,
      playAlbum,
      playTracks,
      playing,
      position,
      previous,
      queue,
      repeat,
      seek,
      shuffle,
      stop,
      toggle,
      toggleShuffle,
      volume,
    ],
  )

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
}

export function usePlayer(): PlayerContextValue {
  const context = useContext(PlayerContext)
  if (!context) throw new Error('usePlayer must be used inside a PlayerProvider')
  return context
}
