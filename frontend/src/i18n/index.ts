import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import { en } from './en'
import { fr } from './fr'

const STORAGE_KEY = 'muzikk.language'

export const SUPPORTED_LANGUAGES = ['fr', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

function detectLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'fr' || stored === 'en') return stored
  } catch {
    /* private browsing */
  }
  const browser = (navigator.language || 'fr').slice(0, 2).toLowerCase()
  return browser === 'en' ? 'en' : 'fr'
}

void i18next.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: detectLanguage(),
  fallbackLng: 'fr',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export function setLanguage(language: Language): void {
  void i18next.changeLanguage(language)
  try {
    window.localStorage.setItem(STORAGE_KEY, language)
  } catch {
    /* private browsing */
  }
  document.documentElement.lang = language
}

export function currentLanguage(): Language {
  return (i18next.language || 'fr').startsWith('en') ? 'en' : 'fr'
}

export function currentLocale(): string {
  return currentLanguage() === 'en' ? 'en-GB' : 'fr-FR'
}

export default i18next
