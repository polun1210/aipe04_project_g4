import { inject, type InjectionKey } from 'vue'

// 前端整合介面，不宣告或猜測正式藥品搜尋的 HTTP 契約。
export interface MedicineCandidate {
  id: string
  name: string
  drugClassCode: string
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
  '正式藥品搜尋尚未開放，暫時無法選取、儲存或確認藥品。辨識資料與圖片會保留。'
const unavailable: MedicineSearchGateway = {
  available: false,
  async search() {
    throw new Error(medicineSearchUnavailable)
  },
}
export function useMedicineSearchGateway(): MedicineSearchGateway {
  return inject(medicineSearchGatewayKey, unavailable)
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
    (value.specification === null || typeof value.specification === 'string') &&
    (value.licenseNumber === null || typeof value.licenseNumber === 'string')
  )
}
