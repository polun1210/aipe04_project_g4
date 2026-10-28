import { computed, readonly, ref, toRaw, type DeepReadonly } from 'vue'
import { defineStore } from 'pinia'
import type { ConfirmedDrug, DrugDraft } from '../api/drugs'

export interface DrugBatch {
  files: File[]
  draft: DeepReadonly<DrugDraft>
}

interface MedicineRowState {
  id: string
  name: string
  draftName: string
  // 尚未完成首次儲存的新列；儲存後為 false，來源仍由 draftId / rowId 判斷。
  isNew: boolean
  isEditing: boolean
  isLocked: boolean
  errorMessage: string
}

export type MedicineRow = MedicineRowState & (
  | { draftId: string; rowId: string }
  | { draftId: null; rowId: null }
)

export const useMedicineFlowStore = defineStore('medicineFlow', () => {
  const drugBatches = ref<DrugBatch[]>([])
  const medicines = ref<MedicineRow[]>([])

  // 僅在評估成功且確認已抵達該份報告後清除本輪資料。
  function resetFlow(): void {
    drugBatches.value = []
    medicines.value = []
  }

  const allConfirmed = computed(
    () => medicines.value.length > 0 && medicines.value.every(
      (medicine) => medicine.name.trim() !== '' && !medicine.isEditing && medicine.isLocked,
    ),
  )

  // 尚未全部確認時不產生可送出的清單；這不會呼叫後端。
  const confirmedDrugs = computed<ConfirmedDrug[]>(() => {
    if (!allConfirmed.value) return []
    return medicines.value.map((medicine) => {
      const name = medicine.name.trim()
      return medicine.draftId === null
        ? { draft_id: null, row_id: null, name }
        : { draft_id: medicine.draftId, row_id: medicine.rowId, name }
    })
  })

  function addDrugBatch(files: readonly File[], draft: DrugDraft): void {
    if (drugBatches.value.some((batch) => batch.draft.draft_id === draft.draft_id)) return

    // 複製陣列即可保留 File 順序；Vue 不會把原生 File 轉為響應式 Proxy。
    // 草稿是 JSON 資料，獨立複製後設為深層唯讀，避免改動呼叫端或原始文字。
    const savedDraft = readonly(structuredClone(toRaw(draft)))
    drugBatches.value.push({ files: [...files], draft: savedDraft })

    const existingIds = new Set(medicines.value.map((medicine) => medicine.id))
    for (const row of savedDraft.rows) {
      const id = `${savedDraft.draft_id}:${row.row_id}`
      if (existingIds.has(id)) continue
      medicines.value.push({
        id,
        draftId: savedDraft.draft_id,
        rowId: row.row_id,
        name: row.raw_name,
        draftName: row.raw_name,
        isNew: false,
        isEditing: false,
        isLocked: false,
        errorMessage: '',
      })
      existingIds.add(id)
    }
  }

  function findDraftRow(draftId: string, rowId: string) {
    return drugBatches.value
      .find((batch) => batch.draft.draft_id === draftId)
      ?.draft.rows.find((row) => row.row_id === rowId)
  }

  function findSourceFile(draftId: string, sourceImageId: string): File | undefined {
    const batch = drugBatches.value.find((item) => item.draft.draft_id === draftId)
    if (!batch?.draft.source_images.some((image) => image.image_id === sourceImageId)) {
      return undefined
    }

    // app/uploads.py 依該批送出順序編為 img-01、img-02…。
    // 不依賴 source_images 的排列，也不在來源不存在時改用第一張。
    const index = batch.files.findIndex((_, i) => `img-${String(i + 1).padStart(2, '0')}` === sourceImageId)
    return batch.files[index]
  }

  function addMedicine(): void {
    medicines.value.push({
      id: crypto.randomUUID(),
      draftId: null,
      rowId: null,
      name: '',
      draftName: '',
      isNew: true,
      isEditing: true,
      isLocked: false,
      errorMessage: '',
    })
  }

  function startEditing(medicine: MedicineRow): void {
    if (medicine.isLocked) return
    medicine.draftName = medicine.name
    medicine.errorMessage = ''
    medicine.isEditing = true
  }

  function removeMedicine(id: string): void {
    medicines.value = medicines.value.filter((medicine) => medicine.id !== id)
  }

  function saveMedicine(medicine: MedicineRow): void {
    if (medicine.isLocked || !medicine.isEditing) return
    const name = medicine.draftName.trim()
    if (!name) {
      if (medicine.isNew) removeMedicine(medicine.id)
      else medicine.errorMessage = '藥名不可空白'
      return
    }
    medicine.name = name
    medicine.draftName = name
    medicine.isNew = false
    medicine.isEditing = false
    medicine.errorMessage = ''
  }

  function cancelEditing(medicine: MedicineRow): void {
    if (medicine.isNew) {
      removeMedicine(medicine.id)
      return
    }
    medicine.draftName = medicine.name
    medicine.isEditing = false
    medicine.errorMessage = ''
  }

  function setLocked(medicine: MedicineRow, locked: boolean): void {
    if (medicine.isEditing || !medicine.name.trim()) return
    medicine.isLocked = locked
  }

  function setAllLocked(locked: boolean): number {
    for (const medicine of medicines.value) setLocked(medicine, locked)
    return medicines.value.filter((medicine) => medicine.isLocked !== locked).length
  }

  return {
    drugBatches,
    medicines,
    allConfirmed,
    confirmedDrugs,
    resetFlow,
    addDrugBatch,
    findDraftRow,
    findSourceFile,
    addMedicine,
    startEditing,
    saveMedicine,
    cancelEditing,
    setLocked,
    setAllLocked,
  }
})
