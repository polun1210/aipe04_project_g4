import { apiRequest } from './client'

// 對照 app/schemas/drug_label.py、label.py、common.py 與 enums.py。
// UUID 和 datetime 在 JSON 中以字串傳遞，不需要建立特殊物件。
export type ScopeStatus = 'in_scope' | 'out_of_scope' | 'unresolved'

export interface DrugCandidate {
  active_ingredient_code: string
  display_name_zh: string
  english_name: string
  matched_name: string
  drug_class_codes: string[]
}

export interface DrugLookupResponse {
  mapped: {
    raw_name: string
    scope_status: ScopeStatus
    active_ingredient_code?: string | null
    display_name_zh?: string | null
    drug_class_codes: string[]
  }
  candidates: DrugCandidate[]
}

export function lookupDrug(name: string): Promise<DrugLookupResponse> {
  return apiRequest<DrugLookupResponse>(`/api/drugs/lookup?${new URLSearchParams({ name })}`)
}

export interface BoundingBox {
  x: number
  y: number
  width: number
  height: number
}

export interface SourceImage {
  image_id: string
  quality_status: 'accepted' | 'rejected'
  reject_reason?:
    | 'blur'
    | 'glare'
    | 'truncated'
    | 'skew'
    | 'low_resolution'
    | 'unsupported_label'
    | 'low_light'
    | null
  image_kind?: 'drug_package' | 'supplement_ingredients' | 'supplement_nutrition' | null
}

export interface ExtractionMeta {
  ocr_version: string
  rule_layer_version: string
  synonym_table_version: string
  extracted_at: string
}

export interface DrugDraftRow {
  row_id: string
  raw_name: string
  generic_name_raw?: string | null
  source_image_id: string
  bbox?: BoundingBox | null
  extraction_confidence?: number | null
  active_ingredient_code?: string | null
  scope_status: ScopeStatus
}

export interface DrugDraft {
  draft_id: string
  source_images: SourceImage[]
  rows: DrugDraftRow[]
  extraction_meta: ExtractionMeta
}

// 對照 case.py 的 ConfirmedDrug；來源與劑量各自必須成對。
export type ConfirmedDrug = {
  name: string
} & ({ draft_id: string; row_id: string } | { draft_id?: null; row_id?: null }) &
  ({ dose_mg: number; times_per_day: number } | { dose_mg?: null; times_per_day?: null })

// 後端已用 Pydantic 驗證格式；只檢查上傳頁與 Store 實際依賴的欄位。
export function isUsableDraft(value: unknown, fileCount: number): value is DrugDraft {
  if (typeof value !== 'object' || value === null) return false
  const draft = value as Partial<DrugDraft>
  if (
    typeof draft.draft_id !== 'string' ||
    !draft.draft_id.trim() ||
    !Array.isArray(draft.rows) ||
    !Array.isArray(draft.source_images) ||
    draft.source_images.length !== fileCount ||
    typeof draft.extraction_meta?.ocr_version !== 'string'
  )
    return false

  const images = draft.source_images
  // findSourceFile 依上傳順序找原圖：img-01 是第 1 張、img-02 是第 2 張…。
  if (!images.every((image, i) => image?.image_id === `img-${String(i + 1).padStart(2, '0')}`))
    return false

  // 校對列需要可用的名稱與來源；不重複驗證列舉、座標或辨識信心值。
  return draft.rows.every(
    (row) =>
      row !== null &&
      typeof row === 'object' &&
      typeof row.row_id === 'string' &&
      row.row_id.trim() !== '' &&
      typeof row.raw_name === 'string' &&
      images.some((image) => image.image_id === row.source_image_id),
  )
}

// 辨識模式由後端決定；ocr_version 為 stub 時，呼叫端才顯示測試資料提醒。
// 呼叫端應在 await 前保留本批 File[] 快照，成功後用同一份快照加入 Store。
export function uploadDrugDraft(files: readonly File[]): Promise<DrugDraft> {
  const body = new FormData()
  for (const file of files) {
    body.append('images', file)
  }
  return apiRequest<DrugDraft>('/api/drug-drafts', { method: 'POST', body })
}
