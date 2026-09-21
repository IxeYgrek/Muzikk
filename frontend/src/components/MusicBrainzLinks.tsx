import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useMusicBrainzBrowseUrl } from '../lib/hooks'
import { musicBrainzUrl } from '../lib/musicbrainz'

export function MusicBrainzLinks({
  groupMbid,
  releaseMbid,
  className,
}: {
  groupMbid: string
  releaseMbid?: string | null
  className?: string
}) {
  const { t } = useTranslation()
  const browse = useMusicBrainzBrowseUrl()

  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      <a
        href={musicBrainzUrl('release-group', groupMbid, browse)}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center justify-center gap-2 text-sm text-brand-300 hover:underline"
      >
        <ExternalLink className="size-3.5" />
        {t('album.openMusicBrainz')}
      </a>
      {releaseMbid && (
        <a
          href={musicBrainzUrl('release', releaseMbid, browse)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center justify-center gap-2 text-sm text-ink-400 hover:text-brand-300 hover:underline"
        >
          <ExternalLink className="size-3.5" />
          {t('album.openRelease')}
        </a>
      )}
    </div>
  )
}
