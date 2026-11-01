import { inject, type InjectionKey } from 'vue'
import type { AccountProfile } from '../models/healthProfile'

// 前端整合介面；實作見 healthProfileApi.ts，由 main.ts provide。
// 只有真正完成後端儲存，save 才可 resolve。首次填寫與日後修改都用 saveProfile。
export interface HealthProfileGateway {
  readonly available: boolean
  loadProfile(): Promise<AccountProfile>
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
  saveProfile: unavailable,
})

export function useHealthProfileGateway(): HealthProfileGateway {
  return inject(healthProfileGatewayKey, unavailableGateway)
}
