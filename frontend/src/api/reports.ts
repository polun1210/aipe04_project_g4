import { apiRequest } from './client'
import type { ConfirmedDrug } from './drugs'

export interface ReportSummary {
  report_id: string
  case_id: string
  generated_at: string
  drug_count: number
  product_count: number
}
export interface Citation {
  citation_id: string
  source: string
  url: string | null
  section: string | null
  quote: string
  population: string
  source_version: string | null
  retrieved_at: string
}
export interface ReportNutrient {
  nutrient_code: string
  display_name_zh: string
  peak_intake_from_supplements: number
  average_intake_from_supplements: number
  intake_from_drugs: number | null
  unit: string
  basis: string
  recommended_total_intake: { reference_type: string; value: number }
  ul: { ul_value: number; ratio: number; exceeded: boolean; scope: string; phrasing: string } | null
  narration: string | null
}
export interface ReportInteraction {
  ingredient_code: string
  display_name_zh: string
  severity: 'priority' | 'attention' | 'info'
  narration: string | null
  requires_professional_review: boolean
  matched_product_ids: string[]
  triggers: {
    rule_id: string
    condition_display_name_zh: string
    reason_zh: string
    advice_code: string
    separation_hours: number | null
    citations: Citation[]
  }[]
}
export interface Report {
  report_id: string
  case_id: string
  generated_at: string
  summary: string
  profile: {
    age: number
    sex: string
    known_conditions: { condition_code: string; display_name_zh: string }[]
    known_conditions_none: boolean
    drugs: { raw_name: string; display_name_zh: string | null }[]
    drugs_none: boolean
  }
  products: { product_id: string; display_name: string }[]
  nutrients: ReportNutrient[]
  interactions: ReportInteraction[]
  disclosures: {
    covered_known_conditions: string[]
    covered_drug_classes: string[]
    covered_nutrients: string[]
    known_conditions_none: boolean
    drugs_none: boolean
    healthy_population_caveat: boolean
    peak_same_day_assumption: boolean
    out_of_scope_ingredients: string[]
    unresolved_ingredients: string[]
    out_of_scope_drugs: string[]
    unresolved_drugs: string[]
    drug_source_not_counted: string[]
  }
}
export function createAssessment(drugs: ConfirmedDrug[], productIds: string[]) {
  return apiRequest<{ case_id: string }>('/api/assessments', {
    method: 'POST',
    body: JSON.stringify({
      drugs: { selected: drugs, none_selected: drugs.length === 0 },
      product_ids: productIds,
    }),
  })
}
export function createReport(caseId: string) {
  return apiRequest<Report>(`/api/assessments/${encodeURIComponent(caseId)}/report`, {
    method: 'POST',
  })
}
export function getReport(reportId: string) {
  return apiRequest<Report>(`/api/reports/${encodeURIComponent(reportId)}`)
}
export function getReports(from = '', to = '') {
  const query = new URLSearchParams()
  if (from) query.set('date_from', from)
  if (to) query.set('date_to', to)
  return apiRequest<ReportSummary[]>(`/api/reports?${query}`)
}
export function taipeiDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}
