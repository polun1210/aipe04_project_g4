import { inject, type InjectionKey } from 'vue'
import type { AccountProfile, ConditionSelection } from '../models/healthProfile'

// 這是前端整合介面，不是尚未確認的 HTTP API 契約。
// API 確認後由 App provide 實作；只有真正完成後端儲存，save 才可 resolve。
export interface HealthProfileGateway {
  readonly available: boolean
  loadProfile(): Promise<AccountProfile>
  saveInitialConditions(conditions: ConditionSelection): Promise<void>
  saveProfile(profile: AccountProfile): Promise<void>
}

export const healthProfileGatewayKey: InjectionKey<HealthProfileGateway> =
  Symbol('healthProfileGateway')
export const healthProfileUnavailable = '健康資料儲存功能尚未開放，資料不會送出或儲存。'
async function unavailable(): Promise<never> {
  throw new Error(healthProfileUnavailable)
}
const unavailableGateway: HealthProfileGateway = Object.freeze({
  available: false,
  loadProfile: unavailable,
  saveInitialConditions: unavailable,
  saveProfile: unavailable,
})

export function useHealthProfileGateway(): HealthProfileGateway {
  return inject(healthProfileGatewayKey, unavailableGateway)
}
