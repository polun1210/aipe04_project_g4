import { getProfile, saveProfile } from '../api/auth'
import type { HealthProfileGateway } from './healthProfileGateway'

export const healthProfileApi: HealthProfileGateway = {
  available: true,
  async loadProfile() {
    const profile = await getProfile()
    if (!profile) throw new Error('尚未填寫健康資料。')
    return profile
  },
  async saveProfile(profile) {
    await saveProfile(profile)
  },
}
