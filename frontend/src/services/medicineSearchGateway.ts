import { inject, type InjectionKey } from 'vue'
import { lookupDrug } from '../api/drugs'

export const UNCERTAIN_DRUG_CLASS = 'other_uncertain'

// 前端整合介面，不宣告或猜測正式藥品搜尋的 HTTP 契約。
export interface MedicineCandidate {
  id: string
  name: string
  drugClassCode: string
  matchedName?: string
  englishName?: string
  specification: string | null
  licenseNumber: string | null
}
export interface MedicineSearchGateway {
  readonly available: boolean
  search(drugClassCode: string, query: string): Promise<MedicineCandidate[]>
}
export const medicineSearchGatewayKey: InjectionKey<MedicineSearchGateway> =
  Symbol('medicineSearchGateway')
export const medicineSearchUnavailable =
  '候選藥品搜尋尚未開放，一般類別暫時無法完成校對。辨識資料與圖片會保留。'
const lookupGateway: MedicineSearchGateway = {
  available: true,
  async search(drugClassCode, query) {
    if (!drugClassCode || drugClassCode === UNCERTAIN_DRUG_CLASS || !query.trim()) return []
    const result = await lookupDrug(query.trim())
    if (
      !Array.isArray(result.candidates) ||
      result.candidates.some(
        (candidate) =>
          !candidate ||
          typeof candidate.active_ingredient_code !== 'string' ||
          !candidate.active_ingredient_code.trim() ||
          typeof candidate.display_name_zh !== 'string' ||
          !candidate.display_name_zh.trim() ||
          !Array.isArray(candidate.drug_class_codes) ||
          candidate.drug_class_codes.some((code) => typeof code !== 'string'),
      )
    )
      throw new Error('藥品搜尋回應無法確認，請重試。')
    return result.candidates
      .filter((candidate) => candidate.drug_class_codes.includes(drugClassCode))
      .map((candidate) => ({
        id: candidate.active_ingredient_code,
        name: candidate.display_name_zh,
        drugClassCode,
        ...(candidate.matched_name ? { matchedName: candidate.matched_name } : {}),
        ...(candidate.english_name ? { englishName: candidate.english_name } : {}),
        specification: null,
        licenseNumber: null,
      }))
  },
}
export function useMedicineSearchGateway(): MedicineSearchGateway {
  return inject(medicineSearchGatewayKey, lookupGateway)
}
export function isMedicineCandidate(value: MedicineCandidate): boolean {
  return (
    !!value &&
    typeof value.id === 'string' &&
    !!value.id.trim() &&
    typeof value.name === 'string' &&
    !!value.name.trim() &&
    typeof value.drugClassCode === 'string' &&
    !!value.drugClassCode.trim() &&
    (value.matchedName === undefined || typeof value.matchedName === 'string') &&
    (value.englishName === undefined || typeof value.englishName === 'string') &&
    (value.specification === null || typeof value.specification === 'string') &&
    (value.licenseNumber === null || typeof value.licenseNumber === 'string')
  )
}
