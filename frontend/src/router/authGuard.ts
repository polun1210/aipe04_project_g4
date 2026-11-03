import type { Me } from '../api/auth'

const loginRequired = new Set([
  'member-center',
  'settings',
  'health-profile',
  'medicine-upload',
  'medicine-review',
  'supplement-upload',
  'supplement-review',
  'report',
  'reports',
  'report-detail',
])
const profileRequired = new Set([
  'medicine-upload',
  'medicine-review',
  'supplement-upload',
  'supplement-review',
])

export const DEFAULT_AFTER_LOGIN = '/medicine-upload'

export interface GuardTarget {
  name?: unknown
  fullPath: string
}

// 只接受站內路徑：以 / 開頭、不以 // 開頭（避免被導到外站）。
export function safeRedirect(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : DEFAULT_AFTER_LOGIN
}

// 回傳要導去的位置；null 表示放行。
export function resolveAuthRedirect(to: GuardTarget, me: Me | null) {
  const name = String(to.name ?? '')
  if (name === 'login') {
    return me ? { path: me.profile_completed ? DEFAULT_AFTER_LOGIN : '/health-profile' } : null
  }
  if (loginRequired.has(name) && !me) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (profileRequired.has(name) && me && !me.profile_completed) {
    return { name: 'health-profile' }
  }
  return null
}
