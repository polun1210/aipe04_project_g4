import { apiRequest } from './client'
import type { Unit } from './supplements'

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
  ingredients: Ingredient[]
}

export interface Ingredient {
  code: string
  category: 'target_nutrient' | 'allowed_ingredient'
  display_name_zh: string
  standard_unit: Unit | null
  accepted_units: Unit[]
}

export function getCatalog() {
  return apiRequest<CatalogResponse>('/api/catalog')
}
