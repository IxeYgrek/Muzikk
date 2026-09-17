import { Compass } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { EmptyState } from '../components/ui'

export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <EmptyState
      icon={<Compass className="size-10" />}
      title="404"
      hint={t('errors.generic')}
      action={
        <Link to="/" className="btn btn-primary">
          {t('nav.home')}
        </Link>
      }
    />
  )
}
