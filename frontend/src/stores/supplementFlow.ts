import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Ingredient } from '../api/catalog'
import type {
  DoseUnit,
  Frequency,
  Numeric,
  SupplementDraft,
  Unit,
  VerificationSubmission,
} from '../api/supplements'

export interface NutrientValues {
  choice: string
  amount: Numeric
  unit: Unit | ''
  form: string
  elemental: Numeric
}
export interface NutrientRow {
  id: string
  rowId: string | null
  rawName: string | null
  sourceImageId: string | null
  value: NutrientValues
  edit: NutrientValues
  editing: boolean
  locked: boolean
  isNew: boolean
  error: string
}
export interface SupplementProduct {
  id: string
  draft: SupplementDraft
  files: File[]
  name: string
  servingSize: Numeric
  doseUnit: DoseUnit | ''
  frequency: Frequency | ''
  times: Numeric
  amount: Numeric
  weekly: Numeric
  onDays: Numeric
  offDays: Numeric
  rows: NutrientRow[]
  savedPayload: string | null
  savedProductId: string | null
}
export function positive(value: Numeric): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}
function nonnegative(value: Numeric): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}
function emptyValues(): NutrientValues {
  return { choice: '', amount: null, unit: '', form: '', elemental: null }
}
export function nutrientError(value: NutrientValues, ingredients: Ingredient[]): string {
  if (!value.choice) return '請選擇營養素或評估範圍。'
  const ingredient = ingredients.find((item) => item.code === value.choice)
  if (!ingredient && !['unresolved', 'out_of_scope'].includes(value.choice))
    return '請重新選擇營養素。'
  if (ingredient?.category === 'target_nutrient' && (!nonnegative(value.amount) || !value.unit))
    return '請填寫每份含量（可為 0）與單位。'
  if (value.amount !== null && value.amount !== '' && !nonnegative(value.amount))
    return '含量不可為負數。'
  if (value.elemental !== null && value.elemental !== '' && !nonnegative(value.elemental))
    return '元素量不可為負數。'
  if (
    ingredient &&
    value.unit &&
    (value.unit === 'other' ||
      (ingredient.accepted_units.length > 0 && !ingredient.accepted_units.includes(value.unit)))
  )
    return '單位不適用此成分，請依標示選擇。'
  return ''
}
export function productReady(product: SupplementProduct, ingredients: Ingredient[]): boolean {
  return (
    product.name.trim() !== '' &&
    positive(product.servingSize) &&
    !!product.doseUnit &&
    !!product.frequency &&
    positive(product.times) &&
    positive(product.amount) &&
    product.rows.length > 0 &&
    product.rows.every(
      (row) => row.locked && !row.editing && !nutrientError(row.value, ingredients),
    ) &&
    (product.frequency !== 'weekly_n_times' || (positive(product.weekly) && product.weekly <= 7)) &&
    (product.frequency !== 'cyclic_on_off' ||
      (positive(product.onDays) && positive(product.offDays)))
  )
}
export function submissionFor(product: SupplementProduct): VerificationSubmission {
  return {
    product_name: product.name.trim(),
    serving_info: {
      serving_size: Number(product.servingSize),
      dose_unit: product.doseUnit as DoseUnit,
    },
    user_intake: {
      frequency_type: product.frequency as Frequency,
      times_per_day: Number(product.times),
      amount_per_time: Number(product.amount),
      days_per_week: product.frequency === 'weekly_n_times' ? Number(product.weekly) : null,
      cycle_on_days: product.frequency === 'cyclic_on_off' ? Number(product.onDays) : null,
      cycle_off_days: product.frequency === 'cyclic_on_off' ? Number(product.offDays) : null,
    },
    nutrients: product.rows.map((row) => {
      const scope = row.value.choice
      return {
        row_id: row.rowId,
        standard_code: ['unresolved', 'out_of_scope'].includes(scope) ? null : scope,
        scope_status: scope === 'unresolved' || scope === 'out_of_scope' ? scope : 'in_scope',
        nutrient_form_code: row.value.form.trim() || null,
        per_serving: nonnegative(row.value.amount) ? row.value.amount : null,
        unit: row.value.unit || null,
        stated_elemental_amount: nonnegative(row.value.elemental) ? row.value.elemental : null,
      }
    }),
  }
}

export const useSupplementFlowStore = defineStore('supplementFlow', () => {
  const products = ref<SupplementProduct[]>([])
  const caseId = ref<string | null>(null)
  function addBatch(files: File[], draft: SupplementDraft) {
    if (products.value.some((product) => product.id === draft.product_id)) return
    products.value.push({
      id: draft.product_id,
      draft: structuredClone(draft),
      files: [...files],
      name: draft.product_name ?? '',
      servingSize: draft.serving_info.serving_size,
      doseUnit: draft.serving_info.dose_unit ?? '',
      frequency: '',
      times: draft.label_suggested_intake?.times_per_day ?? null,
      amount: draft.label_suggested_intake?.amount_per_time ?? null,
      weekly: null,
      onDays: null,
      offDays: null,
      savedPayload: null,
      savedProductId: null,
      rows: draft.nutrients.map((row) => {
        const value: NutrientValues = {
          choice: row.standard_code ?? row.scope_status,
          amount: row.per_serving ?? null,
          unit: row.unit ?? '',
          form: row.nutrient_form_code ?? '',
          elemental: row.stated_elemental_amount ?? null,
        }
        return {
          id: `${draft.product_id}:${row.row_id}`,
          rowId: row.row_id,
          rawName: row.raw_name,
          sourceImageId: row.source_image_id,
          value,
          edit: { ...value },
          editing: false,
          locked: false,
          isNew: false,
          error: '',
        }
      }),
    })
  }
  function addRow(product: SupplementProduct) {
    product.rows.push({
      id: crypto.randomUUID(),
      rowId: null,
      rawName: null,
      sourceImageId: null,
      value: emptyValues(),
      edit: emptyValues(),
      editing: true,
      locked: false,
      isNew: true,
      error: '',
    })
  }
  function editRow(row: NutrientRow) {
    if (row.locked) return
    row.edit = { ...row.value }
    row.editing = true
    row.error = ''
  }
  function cancelRow(product: SupplementProduct, row: NutrientRow) {
    if (row.isNew) product.rows = product.rows.filter((item) => item.id !== row.id)
    else {
      row.editing = false
      row.error = ''
      row.edit = { ...row.value }
    }
  }
  function saveRow(product: SupplementProduct, row: NutrientRow, ingredients: Ingredient[]) {
    if (row.locked) return
    if (!row.edit.choice && row.isNew) {
      cancelRow(product, row)
      return
    }
    row.error = nutrientError(row.edit, ingredients)
    if (row.error) return
    row.value = { ...row.edit }
    row.editing = false
    row.isNew = false
  }
  function setLocked(row: NutrientRow, locked: boolean, ingredients: Ingredient[]) {
    row.error = nutrientError(row.value, ingredients)
    if (!row.editing && !row.error) row.locked = locked
  }
  return { products, caseId, addBatch, addRow, editRow, cancelRow, saveRow, setLocked }
})
