import clsx from 'clsx'
import { Languages } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { setLanguage } from '../i18n'

const CODES = ['en', 'fr'] as const

/** Compact English / French toggle used on the public pages and in the sidebar. */
export function LanguageSwitch({ className }: { className?: string }) {
  const { i18n } = useTranslation()
  const language = (i18n.language || 'en').startsWith('fr') ? 'fr' : 'en'

  return (
    <div className={clsx('flex items-center gap-1 rounded-xl bg-ink-800/60 p-1', className)}>
      <Languages className="ml-1.5 size-3.5 shrink-0 text-ink-500" />
      {CODES.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLanguage(code)}
          className={clsx(
            'flex-1 rounded-lg px-2 py-1 text-xs font-semibold uppercase transition-colors',
            language === code ? 'bg-brand-600/30 text-ink-50' : 'text-ink-400 hover:text-ink-100',
          )}
        >
          {code}
        </button>
      ))}
    </div>
  )
}
