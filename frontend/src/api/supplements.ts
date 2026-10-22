import { apiRequest } from './client'
import type { ExtractionMeta, SourceImage, ScopeStatus } from './drugs'

export type Unit = 'mg' | 'ug' | 'g' | 'kcal' | 'iu' | 'mg_ate' | 'mg_ne' | 'other'
export type DoseUnit =
  'capsule' | 'tablet' | 'softgel' | 'gummy' | 'sachet' | 'scoop' | 'ml' | 'drop' | 'g'
export type Frequency =
  'daily' | 'alternate_days' | 'weekly_n_times' | 'cyclic_on_off' | 'as_needed'
export type Numeric = number | '' | null

// 現有保健食品假辨識回 stub-t01；藥包假辨識回 stub。
export function isTestExtraction(version: string) {
  return version === 'stub' || version.startsWith('stub-')
}

export interface NutrientConfirmed {
  row_id: string | null
  standard_code: string | null
  scope_status: ScopeStatus
  nutrient_form_code: string | null
  per_serving: number | null
  unit: Unit | null
  stated_elemental_amount: number | null
}

export interface NutrientDraft extends NutrientConfirmed {
  row_id: string
  raw_name: string
  source_image_id: string
  requires_user_input: boolean
}

export interface SupplementDraft {
  product_id: string
  product_name: string | null
  source_images: SourceImage[]
  serving_info: { serving_size: number | null; dose_unit: DoseUnit | null }
  label_suggested_intake: {
    raw_text: string
    amount_per_time: number | null
    times_per_day: number | null
  } | null
  nutrients: NutrientDraft[]
  extraction_meta: ExtractionMeta
}

export interface VerificationSubmission {
  product_name: string
  serving_info: { serving_size: number; dose_unit: DoseUnit }
  user_intake: {
    frequency_type: Frequency
    times_per_day: number
    amount_per_time: number
    days_per_week: number | null
    cycle_on_days: number | null
    cycle_off_days: number | null
  }
  nutrients: NutrientConfirmed[]
}

export function uploadSupplementDraft(ingredients: File[], nutrition: File[], category: string) {
  const body = new FormData()
  ingredients.forEach((file) => body.append('ingredient_images', file))
  nutrition.forEach((file) => body.append('nutrition_images', file))
  if (category.trim()) body.append('category', category.trim())
  return apiRequest<SupplementDraft>('/api/supplement-drafts', { method: 'POST', body })
}

export function isUsableSupplementDraft(value: unknown, count: number): value is SupplementDraft {
  if (value === null || typeof value !== 'object') return false
  const draft = value as Partial<SupplementDraft>
  if (
    typeof draft.product_id !== 'string' ||
    !draft.product_id.trim() ||
    !Array.isArray(draft.source_images) ||
    draft.source_images.length !== count ||
    !draft.source_images.every(
      (image, i) => image?.image_id === `img-${String(i + 1).padStart(2, '0')}`,
    ) ||
    !draft.serving_info ||
    typeof draft.serving_info !== 'object' ||
    typeof draft.extraction_meta?.ocr_version !== 'string' ||
    !Array.isArray(draft.nutrients)
  )
    return false
  const images = draft.source_images
  return draft.nutrients.every(
    (row) =>
      row &&
      typeof row.row_id === 'string' &&
      typeof row.raw_name === 'string' &&
      images.some((image) => image.image_id === row.source_image_id),
  )
}

export function createProduct(body: VerificationSubmission) {
  return apiRequest<{ product_id: string }>('/api/products', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export const doseLabels: Record<DoseUnit, string> = {
  capsule: '膠囊',
  tablet: '錠',
  softgel: '軟膠囊',
  gummy: '軟糖',
  sachet: '包',
  scoop: '匙',
  ml: 'mL',
  drop: '滴',
  g: 'g',
}
export const doseAmounts: Record<DoseUnit, number[]> = {
  capsule: [1, 2, 3, 4, 5],
  tablet: [1, 2, 3, 4, 5],
  softgel: [1, 2, 3, 4, 5],
  gummy: [1, 2, 3, 4, 5],
  sachet: [1, 2, 3, 4, 5],
  scoop: [1, 2, 3, 4, 5],
  ml: [1, 2, 5, 10, 15, 20, 30],
  drop: [1, 2, 3, 4, 5, 10, 15, 20],
  g: [1, 2, 3, 5, 10, 15, 20],
}
export const unitOptions: Unit[] = ['mg', 'ug', 'g', 'iu', 'mg_ate', 'mg_ne', 'kcal', 'other']
