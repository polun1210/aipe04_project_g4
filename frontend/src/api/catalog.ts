// API 串接練習，尚未接入正式頁面，待團隊整合

import { apiRequest } from './client'

export interface KnownCondition {
  condition_code: string
  display_name_zh: string
  backend_name: string
  sort_order: number
}

export interface DrugItem {
  active_ingredient_code: string
  display_name_zh: string
  english_name: string
  drug_class_codes: string[]
  common_tradenames_tw: string[]
  related_conditions: string[]
  requires_dose: boolean
}

export interface CatalogResponse {
  known_conditions: KnownCondition[]
  drug_classes: unknown[]
  drug_items: DrugItem[]
  drug_nutrient_doses: unknown[]
  ingredients: unknown[]
}

export function getCatalog() {
  return apiRequest<CatalogResponse>('/api/catalog')
}