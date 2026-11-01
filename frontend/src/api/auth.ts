import { ApiError, apiRequest } from './client'
import type { AccountProfile } from '../models/healthProfile'

export interface Me {
  user_id: string
  email: string | null
  name: string | null
  profile_completed: boolean
}

// 沒登入（401）回 null，其他錯誤照丟。
export async function getMe(): Promise<Me | null> {
  try {
    return await apiRequest<Me>('/api/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export function loginWithGoogle(credential: string) {
  return apiRequest<Me>('/api/auth/google', {
    method: 'POST',
    body: JSON.stringify({ credential }),
  })
}

export function logout() {
  return apiRequest<void>('/api/logout', { method: 'POST' })
}

// 還沒填（404）回 null。
export async function getProfile(): Promise<AccountProfile | null> {
  try {
    return await apiRequest<AccountProfile>('/api/me/profile')
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function saveProfile(profile: AccountProfile) {
  return apiRequest<AccountProfile>('/api/me/profile', {
    method: 'PUT',
    body: JSON.stringify(profile),
  })
}
