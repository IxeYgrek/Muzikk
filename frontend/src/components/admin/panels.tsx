import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Cpu,
  Image,
  KeyRound,
  Library,
  Play,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { currentLocale } from '../../i18n'
import { ApiError, api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { useDebounced, useLocalMode } from '../../lib/hooks'
import type { Indexer, JellyfinLibrary, JobRow, SystemInfo, User } from '../../lib/types'
import { useToast } from '../Toast'
import { Alert, Button, Card, Chip, Field, Input, Modal, Select, Toggle } from '../ui'
import { SettingsFields, SettingsPanel, useSettingsSection } from './SettingsForm'

const JOB_KINDS = [
  'library_sync',
  'users_sync',
  'indexers_sync',
  'watchlist_check',
  'wishlist_retry',
  'retry_failed',
  'prune_events',
]

// Importing Jellyfin users makes no sense without a Jellyfin.
const LOCAL_JOB_KINDS = JOB_KINDS.filter((kind) => kind !== 'users_sync')

function useFail() {
  const { notify } = useToast()
  const { t } = useTranslation()
  return (error: unknown) =>
    notify(error instanceof ApiError ? error.message : t('errors.generic'), 'error')
}

/* ------------------------------------------------------------------ jellyfin */

export function JellyfinPanel() {
  const { t } = useTranslation()
  const [libraries, setLibraries] = useState<JellyfinLibrary[] | null>(null)
  const fail = useFail()

  const load = useMutation({
    mutationFn: () => api<JellyfinLibrary[]>('/admin/jellyfin/libraries', { method: 'POST', body: {} }),
    onSuccess: setLibraries,
    onError: fail,
  })

  return (
    <SettingsPanel
      section="jellyfin"
      testService="jellyfin"
      extra={(values, set) => {
        const selected = (values.music_library_ids as string[]) ?? []
        return (
          <div className="space-y-2 border-t border-ink-600/40 pt-4">
            <div className="flex items-center justify-between gap-3">
              <span className="label mb-0">{t('admin.libraries')}</span>
              <Button size="sm" onClick={() => load.mutate()} loading={load.isPending}>
                <Library className="size-3.5" />
                {t('admin.loadLibraries')}
              </Button>
            </div>

            {libraries === null ? (
              selected.length > 0 && <p className="hint">{selected.join(', ')}</p>
            ) : libraries.length === 0 ? (
              <Alert tone="warning">{t('setup.noLibraries')}</Alert>
            ) : (
              <div className="space-y-1.5">
                {libraries.map((library) => {
                  const checked = selected.includes(library.id)
                  return (
                    <button
                      key={library.id}
                      type="button"
                      onClick={() =>
                        set(
                          'music_library_ids',
                          checked
                            ? selected.filter((id) => id !== library.id)
                            : [...selected, library.id],
                        )
                      }
                      className={clsx(
                        'flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left',
                        checked ? 'border-brand-500/60 bg-brand-600/10' : 'border-ink-600/50',
                      )}
                    >
                      <CheckCircle2
                        className={clsx('size-4 shrink-0', checked ? 'text-brand-400' : 'text-ink-600')}
                      />
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink-100">{library.name}</span>
                        <span className="hint block truncate">{library.locations.join(', ')}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      }}
    />
  )
}

/* -------------------------------------------------------------------- naming */

type NamingPreview = { template: string; examples: string[]; error: string | null }

export function NamingPanel() {
  const { t } = useTranslation()
  const { values, set, dirty, save, loading } = useSettingsSection('naming')
  const template = String(values.album_template ?? '')
  const debounced = useDebounced(template, 500)

  const preview = useQuery({
    queryKey: ['admin', 'naming', 'preview', debounced],
    queryFn: () =>
      api<NamingPreview>('/admin/naming/preview', {
        method: 'POST',
        body: { template: debounced },
      }),
    enabled: Boolean(debounced),
  })

  if (loading) return <Card className="skeleton h-64 rounded-2xl" />

  return (
    <Card className="space-y-5 p-5">
      <SettingsFields section="naming" values={values} set={set} />

      <div className="space-y-3 border-t border-ink-600/40 pt-4">
        <span className="label mb-0">{t('admin.namingPreview')}</span>
        {preview.data?.error && <Alert tone="error">{preview.data.error}</Alert>}
        <div className="space-y-1 rounded-xl bg-ink-950/60 p-3 font-mono text-xs text-ink-300">
          {(preview.data?.examples ?? []).map((example) => (
            <div key={example} className="truncate">
              {example}
            </div>
          ))}
        </div>
        <p className="hint">
          {t('admin.namingVariables')} : {'{albumartist} {album} {year} {date} {track} {title} '}
          {'{artist} {disc} {totaldiscs} {disc_prefix} {artist_prefix} {ext}'}
        </p>
        <Alert tone="info">{t('admin.hardlinkWarning')}</Alert>
      </div>

      <Button
        variant="primary"
        onClick={() => save.mutate(values)}
        loading={save.isPending}
        disabled={!dirty}
      >
        {t('admin.save')}
      </Button>
    </Card>
  )
}

/* ----------------------------------------------------------------- providers */

const PROVIDER_KEYS = ['slskd', 'torrent_public', 'torrent_private']

export function ProvidersPanel() {
  const { t } = useTranslation()
  const { values, set, dirty, save, loading } = useSettingsSection('providers')

  if (loading) return <Card className="skeleton h-48 rounded-2xl" />

  const order: string[] = Array.isArray(values.order)
    ? (values.order as string[])
    : [...PROVIDER_KEYS]

  const move = (index: number, delta: number) => {
    const next = [...order]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    set('order', next)
  }

  return (
    <Card className="space-y-4 p-5">
      <p className="hint">{t('admin.providerOrderHint')}</p>
      <div className="space-y-2">
        {order.map((key, index) => (
          <div
            key={key}
            className="flex items-center gap-3 rounded-xl border border-ink-600/50 bg-ink-800/40 px-3.5 py-3"
          >
            <span className="grid size-7 shrink-0 place-items-center rounded-lg gradient-surface text-xs font-bold text-white">
              {index + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-100">
              {t(`providers.${key}`, key)}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => move(index, -1)}
              disabled={index === 0}
              title={t('admin.moveUp')}
            >
              <ArrowUp className="size-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => move(index, 1)}
              disabled={index === order.length - 1}
              title={t('admin.moveDown')}
            >
              <ArrowDown className="size-3.5" />
            </Button>
          </div>
        ))}
      </div>
      <Button
        variant="primary"
        onClick={() => save.mutate(values)}
        loading={save.isPending}
        disabled={!dirty}
      >
        {t('admin.save')}
      </Button>
    </Card>
  )
}

/* ------------------------------------------------------------------ indexers */

export function IndexersPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const fail = useFail()

  const indexers = useQuery({
    queryKey: ['admin', 'indexers'],
    queryFn: () => api<Indexer[]>('/admin/indexers'),
  })

  const sync = useMutation({
    mutationFn: () => api<Record<string, number>>('/admin/indexers/sync', { method: 'POST' }),
    onSuccess: (result) => {
      notify(`${result.total ?? 0} ${t('admin.sections.indexers')}`, 'success')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'indexers'] })
    },
    onError: fail,
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, unknown> }) =>
      api<Indexer>(`/admin/indexers/${id}`, { method: 'PATCH', body: patch }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['admin', 'indexers'] }),
    onError: fail,
  })

  const rows = indexers.data ?? []

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => sync.mutate()} loading={sync.isPending}>
          <RefreshCw className="size-4" />
          {t('admin.indexerSync')}
        </Button>
      </div>

      {rows.length === 0 ? (
        <Alert tone="info">{t('admin.indexerEmpty')}</Alert>
      ) : (
        <Card className="divide-y divide-ink-700/40">
          {rows.map((indexer) => (
            <div key={indexer.id} className="flex flex-wrap items-center gap-3 p-3.5">
              <div className="min-w-40 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium text-ink-100">{indexer.name}</span>
                  <Chip tone={indexer.privacy === 'private' ? 'warning' : 'muted'}>
                    {indexer.privacy === 'private'
                      ? t('admin.indexerPrivate')
                      : t('admin.indexerPublic')}
                  </Chip>
                  {indexer.supports_music_search && <Chip tone="brand">music</Chip>}
                </div>
                <div className="hint">#{indexer.prowlarr_id} · {indexer.protocol}</div>
              </div>

              <label className="flex items-center gap-1.5 text-xs text-ink-400">
                {t('common.priority')}
                <input
                  type="number"
                  defaultValue={indexer.priority}
                  onBlur={(event) =>
                    update.mutate({
                      id: indexer.id,
                      patch: { priority: Number(event.target.value) },
                    })
                  }
                  className="field w-20 px-2 py-1 text-xs"
                />
              </label>

              <label className="flex items-center gap-1.5 text-xs text-ink-400">
                {t('admin.minSeeders')}
                <input
                  type="number"
                  defaultValue={indexer.min_seeders}
                  onBlur={(event) =>
                    update.mutate({
                      id: indexer.id,
                      patch: { min_seeders: Number(event.target.value) },
                    })
                  }
                  className="field w-20 px-2 py-1 text-xs"
                />
              </label>

              <Select
                value={indexer.privacy}
                onChange={(event) =>
                  update.mutate({ id: indexer.id, patch: { privacy: event.target.value } })
                }
                className="w-auto px-2 py-1 text-xs"
              >
                <option value="public">{t('admin.indexerPublic')}</option>
                <option value="private">{t('admin.indexerPrivate')}</option>
              </Select>

              <div className="w-40">
                <Toggle
                  label={indexer.enabled ? t('common.enabled') : t('common.disabled')}
                  checked={indexer.enabled}
                  onChange={(value) =>
                    update.mutate({ id: indexer.id, patch: { enabled: value } })
                  }
                />
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

/* --------------------------------------------------------------------- users */

/** Create a local account, or reset the password of one. */
function AccountModal({
  mode,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  mode: 'create' | 'password'
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (values: { username: string; password: string; name: string; isAdmin: boolean }) => void
}) {
  const { t } = useTranslation()
  const [username, setUsername] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)

  const ready =
    password.length >= 8 && (mode === 'password' || username.trim().length >= 3)

  return (
    <Modal
      open
      onClose={onClose}
      title={mode === 'create' ? t('admin.userCreate') : t('admin.userResetPassword')}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!ready}
            onClick={() => onSubmit({ username: username.trim(), password, name: name.trim(), isAdmin })}
          >
            {t('common.confirm')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {mode === 'create' && (
          <>
            <Field label={t('auth.username')} hint={t('setup.usernameHint')}>
              <Input value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
            </Field>
            <Field label={t('setup.displayName')}>
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
          </>
        )}
        <Field label={t('auth.password')} hint={t('setup.passwordHint')}>
          <Input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            autoFocus={mode === 'password'}
          />
        </Field>
        {mode === 'create' && (
          <Toggle
            label={t('admin.userAdmin')}
            hint={t('admin.userAdminHint')}
            checked={isAdmin}
            onChange={setIsAdmin}
          />
        )}
        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Modal>
  )
}

export function UsersPanel() {
  const { t } = useTranslation()
  const locale = currentLocale()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const fail = useFail()
  const localMode = useLocalMode()

  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<User | null>(null)
  const [modalError, setModalError] = useState<string | null>(null)

  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api<User[]>('/admin/users'),
  })

  const reload = () => void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })

  const sync = useMutation({
    mutationFn: () => api<Record<string, number>>('/admin/users/sync', { method: 'POST' }),
    onSuccess: (result) => {
      notify(`${result.imported ?? 0} / ${result.total ?? 0}`, 'success')
      reload()
    },
    onError: fail,
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Record<string, unknown> }) =>
      api<User>(`/admin/users/${id}`, { method: 'PATCH', body: patch }),
    onSuccess: reload,
    onError: fail,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<User>('/admin/users', { method: 'POST', body }),
    onSuccess: () => {
      notify(t('admin.userCreated'), 'success')
      setCreating(false)
      reload()
    },
    onError: (error) =>
      setModalError(error instanceof ApiError ? error.message : t('errors.generic')),
  })

  const resetPassword = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api(`/admin/users/${id}/password`, { method: 'POST', body: { password } }),
    onSuccess: () => {
      notify(t('admin.userPasswordChanged'), 'success')
      setResetting(null)
    },
    onError: (error) =>
      setModalError(error instanceof ApiError ? error.message : t('errors.generic')),
  })

  const remove = useMutation({
    mutationFn: (id: number) => api(`/admin/users/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      notify(t('admin.userDeleted'), 'success')
      reload()
    },
    onError: fail,
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {localMode ? (
          <Button
            variant="primary"
            onClick={() => {
              setModalError(null)
              setCreating(true)
            }}
          >
            <UserPlus className="size-4" />
            {t('admin.userCreate')}
          </Button>
        ) : (
          <Button onClick={() => sync.mutate()} loading={sync.isPending}>
            <Users className="size-4" />
            {t('admin.usersSync')}
          </Button>
        )}
      </div>

      <div className="space-y-3">
        {(users.data ?? []).map((user) => (
          <Card key={user.id} className="overflow-hidden p-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700/40 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-full gradient-surface text-sm font-bold text-white">
                  {user.name.slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-ink-100">{user.name}</span>
                    {user.username && <Chip tone="muted">{user.username}</Chip>}
                    {user.is_admin && (
                      <Chip tone="brand">
                        <ShieldCheck className="size-3" />
                        {t('admin.userAdmin')}
                      </Chip>
                    )}
                  </div>
                  <div className="hint">
                    {t('admin.userLastLogin')} ·{' '}
                    {user.last_login_at ? formatDateTime(user.last_login_at, locale) : t('common.never')}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {localMode && (
                  <>
                    <Button
                      size="sm"
                      onClick={() => {
                        setModalError(null)
                        setResetting(user)
                      }}
                      title={t('admin.userResetPassword')}
                    >
                      <KeyRound className="size-3.5" />
                      {t('admin.userResetPassword')}
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      loading={remove.isPending}
                      onClick={() => {
                        if (window.confirm(t('admin.userDeleteConfirm', { name: user.name }))) {
                          remove.mutate(user.id)
                        }
                      }}
                      title={t('admin.userDelete')}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </>
                )}
                <div className="min-w-[14rem]">
                  <Toggle
                    label={t('admin.userEnabled')}
                    hint={t('admin.userEnabledHint')}
                    checked={user.is_enabled}
                    onChange={(value) =>
                      update.mutate({ id: user.id, patch: { is_enabled: value } })
                    }
                  />
                </div>
              </div>
            </div>

            <div className="grid gap-5 p-4 lg:grid-cols-2">
              <section className="space-y-2">
                <h3 className="label mb-0">{t('admin.userPermissions')}</h3>
                <div className="space-y-2 rounded-xl bg-ink-800/50 p-3">
                  <Toggle
                    label={t('admin.userCanRequest')}
                    hint={t('admin.userCanRequestHint')}
                    checked={user.can_request}
                    onChange={(value) =>
                      update.mutate({ id: user.id, patch: { can_request: value } })
                    }
                  />
                  <Toggle
                    label={t('admin.userCanRequestTrack')}
                    hint={t('admin.userCanRequestTrackHint')}
                    checked={user.can_request_track}
                    onChange={(value) =>
                      update.mutate({ id: user.id, patch: { can_request_track: value } })
                    }
                  />
                  <Toggle
                    label={t('admin.userCanUpgrade')}
                    hint={t('admin.userCanUpgradeHint')}
                    checked={user.can_upgrade}
                    onChange={(value) =>
                      update.mutate({ id: user.id, patch: { can_upgrade: value } })
                    }
                  />
                  <Toggle
                    label={t('admin.userCanImport')}
                    hint={t('admin.userCanImportHint')}
                    checked={user.can_import}
                    onChange={(value) =>
                      update.mutate({ id: user.id, patch: { can_import: value } })
                    }
                  />
                  {localMode && (
                    <Toggle
                      label={t('admin.userAdmin')}
                      hint={t('admin.userAdminHint')}
                      checked={user.is_admin}
                      onChange={(value) =>
                        update.mutate({ id: user.id, patch: { is_admin: value } })
                      }
                    />
                  )}
                </div>
              </section>

              <section className="space-y-2">
                <h3 className="label mb-0">{t('admin.userRules')}</h3>
                <div className="space-y-3 rounded-xl bg-ink-800/50 p-3">
                  <Field
                    label={t('admin.userAutoApprove')}
                    hint={t('admin.userAutoApproveHint')}
                  >
                    <Select
                      value={
                        user.auto_approve === null ? 'inherit' : user.auto_approve ? 'yes' : 'no'
                      }
                      onChange={(event) =>
                        update.mutate({
                          id: user.id,
                          patch: {
                            auto_approve:
                              event.target.value === 'inherit'
                                ? null
                                : event.target.value === 'yes',
                          },
                        })
                      }
                    >
                      <option value="inherit">{t('admin.userAutoApproveInherit')}</option>
                      <option value="yes">{t('common.yes')}</option>
                      <option value="no">{t('common.no')}</option>
                    </Select>
                  </Field>
                  <Field label={t('admin.userQuota')} hint={t('admin.quotaUnlimited')}>
                    <Input
                      type="number"
                      min={0}
                      defaultValue={user.weekly_quota}
                      onBlur={(event) =>
                        update.mutate({
                          id: user.id,
                          patch: { weekly_quota: Number(event.target.value) },
                        })
                      }
                    />
                  </Field>
                </div>
              </section>
            </div>
          </Card>
        ))}
      </div>

      {creating && (
        <AccountModal
          mode="create"
          busy={create.isPending}
          error={modalError}
          onClose={() => setCreating(false)}
          onSubmit={(values) =>
            create.mutate({
              username: values.username,
              password: values.password,
              name: values.name,
              is_admin: values.isAdmin,
            })
          }
        />
      )}

      {resetting && (
        <AccountModal
          mode="password"
          busy={resetPassword.isPending}
          error={modalError}
          onClose={() => setResetting(null)}
          onSubmit={(values) =>
            resetPassword.mutate({ id: resetting.id, password: values.password })
          }
        />
      )}
    </div>
  )
}

/* -------------------------------------------------------------------- system */

export function SystemPanel() {
  const { t } = useTranslation()
  const locale = currentLocale()
  const queryClient = useQueryClient()
  const { notify } = useToast()
  const fail = useFail()
  const localMode = useLocalMode()

  const system = useQuery({
    queryKey: ['admin', 'system'],
    queryFn: () => api<SystemInfo>('/admin/system'),
  })

  const jobs = useQuery({
    queryKey: ['admin', 'jobs'],
    queryFn: () => api<JobRow[]>('/admin/jobs', { query: { limit: 40 } }),
    refetchInterval: 10_000,
  })

  const run = useMutation({
    mutationFn: (kind: string) => api(`/admin/jobs/${kind}`, { method: 'POST' }),
    onSuccess: () => {
      notify(t('admin.jobRun'), 'success')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'jobs'] })
    },
    onError: fail,
  })

  const purgeCovers = useMutation({
    mutationFn: () => api<{ removed: number }>('/admin/covers/purge', { method: 'POST' }),
    onSuccess: (result) => notify(t('admin.coversPurged', { count: result.removed }), 'success'),
    onError: fail,
  })

  const info = system.data

  return (
    <div className="space-y-5">
      <Card className="grid gap-4 p-5 sm:grid-cols-2">
        <Info label="Version" value={info?.version} />
        <Info label={t('admin.mode')} value={info ? t(`admin.modes.${info.mode}`, info.mode) : undefined} />
        <Info label="Config" value={info?.config_dir} />
        <Info label={t('fields.naming.music_dir')} value={info?.music_dir} />
        <Info label="Workers" value={info ? String(info.worker_concurrency) : undefined} />
        <div className="sm:col-span-2">
          <div className="label">{t('admin.title')}</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(info?.configured ?? {}).map(([key, ok]) => (
              <Chip key={key} tone={ok ? 'success' : 'muted'}>
                <Cpu className="size-3" />
                {key}
              </Chip>
            ))}
          </div>
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div className="label mb-0">{t('admin.jobs')}</div>
        <div className="flex flex-wrap gap-2">
          {(localMode ? LOCAL_JOB_KINDS : JOB_KINDS).map((kind) => (
            <Button key={kind} size="sm" onClick={() => run.mutate(kind)} disabled={run.isPending}>
              <Play className="size-3.5" />
              {t(`admin.jobKinds.${kind}`, kind)}
            </Button>
          ))}
          <Button size="sm" onClick={() => purgeCovers.mutate()} loading={purgeCovers.isPending}>
            <Image className="size-3.5" />
            {t('admin.purgeCovers')}
          </Button>
        </div>

        <div className="max-h-96 divide-y divide-ink-700/40 overflow-y-auto rounded-xl border border-ink-700/40">
          {(jobs.data ?? []).map((job) => (
            <div key={job.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
              <span className="min-w-40 flex-1 truncate text-ink-200">
                {t(`admin.jobKinds.${job.kind}`, job.kind)}
                {job.request_id ? ` #${job.request_id}` : ''}
              </span>
              <Chip
                tone={
                  job.state === 'done'
                    ? 'success'
                    : job.state === 'failed'
                      ? 'danger'
                      : job.state === 'running'
                        ? 'brand'
                        : 'muted'
                }
              >
                {job.state}
              </Chip>
              <span className="text-xs text-ink-500">
                {formatDateTime(job.finished_at ?? job.started_at ?? job.run_after, locale)}
              </span>
              {job.error && (
                <span className="w-full truncate text-xs text-accent-300" title={job.error}>
                  {job.error}
                </span>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function Info({ label, value }: { label: string; value?: string }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className="truncate font-mono text-sm text-ink-200">{value ?? '—'}</div>
    </div>
  )
}
