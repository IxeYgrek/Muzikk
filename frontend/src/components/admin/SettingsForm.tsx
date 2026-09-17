import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, PlugZap, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, api } from '../../lib/api'
import type { TestResult } from '../../lib/types'
import { useToast } from '../Toast'
import { Alert, Button, Card, Field, Input, Select, Toggle } from '../ui'

export type FieldSpec = {
  key: string
  type: 'text' | 'password' | 'number' | 'bool' | 'list' | 'numberList' | 'select'
  options?: { value: string; label: string }[]
  step?: number
  min?: number
  placeholder?: string
  full?: boolean
}

export const SECTION_FIELDS: Record<string, FieldSpec[]> = {
  general: [
    {
      key: 'default_language',
      type: 'select',
      options: [
        { value: 'fr', label: 'Français' },
        { value: 'en', label: 'English' },
      ],
    },
    { key: 'default_weekly_quota', type: 'number', min: 0 },
    { key: 'require_approval', type: 'bool', full: true },
    { key: 'admins_bypass_approval', type: 'bool', full: true },
    { key: 'retry_failed_after_hours', type: 'number', min: 1 },
    { key: 'max_retry_attempts', type: 'number', min: 1 },
    { key: 'library_scan_interval_minutes', type: 'number', min: 5 },
    { key: 'watchlist_check_interval_hours', type: 'number', min: 1 },
    { key: 'keep_events_days', type: 'number', min: 1 },
  ],
  jellyfin: [
    { key: 'url', type: 'text', placeholder: 'http://jellyfin:8096', full: true },
    { key: 'api_key', type: 'password', full: true },
    { key: 'trigger_scan_on_import', type: 'bool', full: true },
    { key: 'allow_all_users', type: 'bool', full: true },
    { key: 'allowed_user_ids', type: 'list', full: true },
  ],
  musicbrainz: [
    { key: 'url', type: 'text', placeholder: 'http://musicbrainz:5000', full: true },
    { key: 'use_public_fallback', type: 'bool', full: true },
    { key: 'public_url', type: 'text', full: true },
    { key: 'rate_limit_per_second', type: 'number', step: 0.5, min: 0.1 },
    { key: 'public_rate_limit_per_second', type: 'number', step: 0.5, min: 0.1 },
    { key: 'contact', type: 'text', full: true },
  ],
  coverart: [
    { key: 'url', type: 'text', full: true },
    { key: 'preferred_size', type: 'number', min: 250 },
    { key: 'embed_in_files', type: 'bool', full: true },
    { key: 'save_folder_cover', type: 'bool', full: true },
    { key: 'save_folder_jpg', type: 'bool', full: true },
  ],
  slskd: [
    { key: 'enabled', type: 'bool', full: true },
    { key: 'url', type: 'text', placeholder: 'http://slskd:5030', full: true },
    { key: 'api_key', type: 'password', full: true },
    { key: 'url_base', type: 'text' },
    { key: 'downloads_dir', type: 'text' },
    { key: 'search_timeout_ms', type: 'number', min: 2000 },
    { key: 'response_limit', type: 'number', min: 10 },
    { key: 'min_peer_upload_speed', type: 'number', min: 0 },
    { key: 'max_peer_queue_length', type: 'number', min: 0 },
    { key: 'wait_timeout_minutes', type: 'number', min: 1 },
    { key: 'stall_timeout_minutes', type: 'number', min: 1 },
    { key: 'remove_completed', type: 'bool', full: true },
  ],
  prowlarr: [
    { key: 'enabled', type: 'bool', full: true },
    { key: 'url', type: 'text', placeholder: 'http://prowlarr:9696', full: true },
    { key: 'api_key', type: 'password', full: true },
    { key: 'categories', type: 'numberList', full: true },
    { key: 'result_limit', type: 'number', min: 10 },
    { key: 'use_music_search', type: 'bool', full: true },
    { key: 'inspect_torrent_files', type: 'bool', full: true },
  ],
  qbittorrent: [
    { key: 'enabled', type: 'bool', full: true },
    { key: 'url', type: 'text', placeholder: 'http://qbittorrent:8080', full: true },
    { key: 'username', type: 'text' },
    { key: 'password', type: 'password' },
    { key: 'category', type: 'text' },
    { key: 'save_path', type: 'text' },
    { key: 'wait_timeout_minutes', type: 'number', min: 1 },
    { key: 'stall_timeout_minutes', type: 'number', min: 1 },
    { key: 'keep_seeding', type: 'bool', full: true },
    { key: 'add_paused', type: 'bool', full: true },
  ],
  quality: [
    { key: 'lossless_formats', type: 'list', full: true },
    { key: 'allow_lossy_fallback', type: 'bool', full: true },
    { key: 'lossy_formats', type: 'list', full: true },
    { key: 'min_lossy_bitrate', type: 'number', min: 96 },
    { key: 'prefer_24bit', type: 'bool', full: true },
    { key: 'min_score', type: 'number', step: 1, min: 0 },
    { key: 'track_count_tolerance', type: 'number', min: 0 },
    { key: 'min_seeders', type: 'number', min: 0 },
    { key: 'min_size_per_track_mb', type: 'number', step: 0.5, min: 0 },
    { key: 'max_size_per_track_mb', type: 'number', step: 1, min: 1 },
    { key: 'verify_audio_integrity', type: 'bool', full: true },
    { key: 'reject_incomplete_albums', type: 'bool', full: true },
    { key: 'require_artist_match', type: 'bool', full: true },
  ],
  metadata: [
    { key: 'nightly_scan', type: 'bool', full: true },
    { key: 'scan_hour', type: 'number', min: 0 },
    { key: 'min_tracks_per_album', type: 'number', min: 1 },
    { key: 'max_albums_per_scan', type: 'number', min: 100 },
    { key: 'confident_score', type: 'number', step: 1, min: 50 },
    { key: 'embed_cover', type: 'bool', full: true },
    { key: 'write_folder_cover', type: 'bool', full: true },
    { key: 'write_folder_jpg', type: 'bool', full: true },
    { key: 'acoustid_enabled', type: 'bool', full: true },
    { key: 'acoustid_api_key', type: 'password', full: true },
    { key: 'acoustid_sample_tracks', type: 'number', min: 1 },
  ],
  player: [
    { key: 'enabled', type: 'bool', full: true },
    { key: 'direct_file_access', type: 'bool', full: true },
    { key: 'previews', type: 'bool', full: true },
    { key: 'max_bitrate', type: 'number', min: 0 },
    { key: 'report_playback', type: 'bool', full: true },
  ],
  naming: [
    { key: 'album_template', type: 'text', full: true },
    { key: 'music_dir', type: 'text', full: true },
    { key: 'replace_unsafe_with', type: 'text' },
    { key: 'max_component_length', type: 'number', min: 40 },
    { key: 'various_artists_name', type: 'text', full: true },
    { key: 'use_hardlinks', type: 'bool', full: true },
    { key: 'overwrite_on_upgrade', type: 'bool', full: true },
    { key: 'confirm_upgrade_replace', type: 'bool', full: true },
  ],
}

type Values = Record<string, unknown>

export function useSettingsSection(section: string) {
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const { t } = useTranslation()
  const [values, setValues] = useState<Values>({})
  const [dirty, setDirty] = useState(false)

  const query = useQuery({
    queryKey: ['admin', 'settings', section],
    queryFn: () => api<Values>(`/admin/settings/${section}`),
  })

  // Drop everything the previous section left behind, otherwise its values
  // would be saved into this one.
  const [loadedSection, setLoadedSection] = useState(section)
  if (loadedSection !== section) {
    setLoadedSection(section)
    setValues({})
    setDirty(false)
  }

  useEffect(() => {
    if (query.data && !dirty) setValues(query.data)
  }, [query.data, dirty])

  const save = useMutation({
    mutationFn: (payload: Values) =>
      api<Values>(`/admin/settings/${section}`, { method: 'PUT', body: payload }),
    onSuccess: (saved) => {
      setValues(saved)
      setDirty(false)
      notify(t('common.saved'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['admin'] })
      void queryClient.invalidateQueries({ queryKey: ['health'] })
    },
    onError: (error) =>
      notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error'),
  })

  const set = (key: string, value: unknown) => {
    setDirty(true)
    setValues((current) => ({ ...current, [key]: value }))
  }

  return { values, set, dirty, save, loading: query.isLoading }
}

export function ConnectionTest({
  service,
  overrides,
}: {
  service: string
  overrides: Values
}) {
  const { t } = useTranslation()
  const [result, setResult] = useState<TestResult | null>(null)

  const test = useMutation({
    mutationFn: () =>
      api<TestResult>(`/admin/test/${service}`, { method: 'POST', body: overrides }),
    onSuccess: setResult,
    onError: (error) =>
      setResult({
        ok: false,
        message: error instanceof ApiError ? error.message : t('errors.generic'),
        details: {},
      }),
  })

  return (
    <div className="space-y-2">
      <Button onClick={() => test.mutate()} loading={test.isPending}>
        <PlugZap className="size-4" />
        {test.isPending ? t('common.testing') : t('common.test')}
      </Button>
      {result && (
        <Alert tone={result.ok ? 'success' : 'error'} className="flex items-start gap-2">
          {result.ok ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          ) : (
            <XCircle className="mt-0.5 size-4 shrink-0" />
          )}
          <span className="min-w-0 break-words">
            {result.message || (result.ok ? t('admin.testOk') : t('admin.testFailed'))}
          </span>
        </Alert>
      )}
    </div>
  )
}

export function SettingsFields({
  section,
  values,
  set,
}: {
  section: string
  values: Values
  set: (key: string, value: unknown) => void
}) {
  const { t } = useTranslation()
  const fields = SECTION_FIELDS[section] ?? []

  return (
    <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2">
      {fields.map((spec) => {
        const label = t(`fields.${section}.${spec.key}`, spec.key)
        const value = values[spec.key]
        const className = spec.full ? 'sm:col-span-2' : undefined

        if (spec.type === 'bool') {
          return (
            <div key={spec.key} className={className}>
              <Toggle
                label={label}
                checked={Boolean(value)}
                onChange={(next) => set(spec.key, next)}
              />
            </div>
          )
        }

        if (spec.type === 'select') {
          return (
            <Field key={spec.key} label={label} className={className}>
              <Select
                value={String(value ?? '')}
                onChange={(event) => set(spec.key, event.target.value)}
              >
                {(spec.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
          )
        }

        if (spec.type === 'list' || spec.type === 'numberList') {
          const text = Array.isArray(value) ? value.join(', ') : ''
          return (
            <Field key={spec.key} label={label} className={className} hint={t('common.optional')}>
              <Input
                value={text}
                placeholder={spec.placeholder}
                onChange={(event) => {
                  const parts = event.target.value
                    .split(',')
                    .map((part) => part.trim())
                    .filter(Boolean)
                  set(
                    spec.key,
                    spec.type === 'numberList'
                      ? parts.map(Number).filter((item) => !Number.isNaN(item))
                      : parts,
                  )
                }}
              />
            </Field>
          )
        }

        return (
          <Field
            key={spec.key}
            label={label}
            className={className}
            hint={spec.type === 'password' ? t('admin.secretKept') : undefined}
          >
            <Input
              type={spec.type === 'password' ? 'password' : spec.type === 'number' ? 'number' : 'text'}
              value={value === null || value === undefined ? '' : String(value)}
              placeholder={spec.placeholder}
              step={spec.step}
              min={spec.min}
              autoComplete={spec.type === 'password' ? 'new-password' : undefined}
              onChange={(event) =>
                set(
                  spec.key,
                  spec.type === 'number'
                    ? event.target.value === ''
                      ? 0
                      : Number(event.target.value)
                    : event.target.value,
                )
              }
            />
          </Field>
        )
      })}
    </div>
  )
}

export function SettingsPanel({
  section,
  testService,
  extra,
  footer,
}: {
  section: string
  testService?: string
  extra?: (values: Values, set: (key: string, value: unknown) => void) => ReactNode
  footer?: ReactNode
}) {
  const { t } = useTranslation()
  const { values, set, dirty, save, loading } = useSettingsSection(section)

  if (loading) return <Card className="skeleton h-64 rounded-2xl" />

  return (
    <div className="space-y-5">
      <Card className="space-y-5 p-5">
        <SettingsFields section={section} values={values} set={set} />
        {extra?.(values, set)}
        <div className="flex flex-wrap items-center gap-3 border-t border-ink-600/40 pt-4">
          <Button
            variant="primary"
            onClick={() => save.mutate(values)}
            loading={save.isPending}
            disabled={!dirty}
          >
            {save.isPending ? t('common.saving') : t('admin.save')}
          </Button>
          {testService && <ConnectionTest service={testService} overrides={values} />}
        </div>
      </Card>
      {footer}
    </div>
  )
}
