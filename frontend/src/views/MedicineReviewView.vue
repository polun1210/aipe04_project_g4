<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import {
  useMedicineFlowStore,
  hasValidMedicineReview,
  type MedicineRow,
} from '../stores/medicineFlow'
import { getCatalog, type DrugClass } from '../api/catalog'
import {
  isMedicineCandidate,
  UNCERTAIN_DRUG_CLASS,
  medicineSearchUnavailable,
  useMedicineSearchGateway,
  type MedicineCandidate,
} from '../services/medicineSearchGateway'
import { errorMessage } from '../api/client'
import ReviewImageGallery from '../components/ReviewImageGallery.vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const flow = useMedicineFlowStore()
function goNext() {
  if (!flow.allConfirmed) return
  void router.push('/supplement-upload')
}
const { medicines, allConfirmed } = storeToRefs(flow)
const bulkMessage = ref('')
const selectedImageId = ref('')
const searchGateway = useMedicineSearchGateway()
const catalogClasses = ref<DrugClass[]>([])
const catalogLoading = ref(false)
const catalogError = ref('')
const drugClasses = ref<Record<string, string>>({})
const searchTimers = new Map<string, ReturnType<typeof setTimeout>>()
let disposed = false
function classFor(medicine: MedicineRow) {
  return (
    drugClasses.value[medicine.id] ??
    (medicine.reviewMode === 'uncertain'
      ? UNCERTAIN_DRUG_CLASS
      : (medicine.selectedMedicine?.drugClassCode ?? ''))
  )
}
async function loadClasses() {
  if (catalogLoading.value) return
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const result = await getCatalog()
    if (
      !Array.isArray(result.drug_classes) ||
      result.drug_classes.some(
        (item) =>
          !item ||
          typeof item.drug_class_code !== 'string' ||
          typeof item.display_name_zh !== 'string' ||
          typeof item.plain_description_zh !== 'string',
      )
    )
      throw new Error('Invalid drug classes')
    if (!disposed) catalogClasses.value = result.drug_classes
  } catch (reason) {
    if (!disposed) catalogError.value = errorMessage(reason)
  } finally {
    catalogLoading.value = false
  }
}
const confirmedCount = computed(
  () =>
    medicines.value.filter(
      (medicine) => medicine.isLocked && !medicine.isEditing && hasValidMedicineReview(medicine),
    ).length,
)
const lookups = ref<
  Record<
    string,
    {
      loading: boolean
      result: { candidates: MedicineCandidate[] } | null
      selected: MedicineCandidate | null
      query: string
      drugClassCode: string
      error: string
    }
  >
>({})

function setAllLocked(locked: boolean): void {
  const skipped = flow.setAllLocked(locked)
  bulkMessage.value = skipped
    ? `有 ${skipped} 筆無法鎖定：請先完成藥品校對，並儲存或取消編輯，再按「一鍵鎖定」。其他可鎖定的藥品已鎖定。`
    : locked
      ? '全部藥品已鎖定，尚未送出評估。'
      : '全部藥品已解除鎖定。'
}

function clearLookup(medicine: MedicineRow): void {
  clearTimeout(searchTimers.get(medicine.id))
  searchTimers.delete(medicine.id)
  delete lookups.value[medicine.id]
  medicine.errorMessage = ''
}

function inputChanged(medicine: MedicineRow) {
  clearLookup(medicine)
  if (
    searchGateway.available &&
    classFor(medicine) &&
    classFor(medicine) !== UNCERTAIN_DRUG_CLASS &&
    medicine.draftName.trim()
  ) {
    searchTimers.set(
      medicine.id,
      setTimeout(() => {
        searchTimers.delete(medicine.id)
        void searchDrug(medicine)
      }, 300),
    )
  }
}
function changeClass(medicine: MedicineRow, event: Event) {
  drugClasses.value[medicine.id] = (event.target as HTMLSelectElement).value
  inputChanged(medicine)
}

async function searchDrug(medicine: MedicineRow): Promise<void> {
  const name = medicine.draftName.trim()
  const drugClassCode = classFor(medicine)
  clearTimeout(searchTimers.get(medicine.id))
  searchTimers.delete(medicine.id)
  if (
    !name ||
    !drugClassCode ||
    !catalogClasses.value.some((item) => item.drug_class_code === drugClassCode) ||
    !medicine.isEditing ||
    medicine.isLocked ||
    disposed
  )
    return
  if (
    lookups.value[medicine.id]?.loading &&
    lookups.value[medicine.id]?.query === name &&
    lookups.value[medicine.id]?.drugClassCode === drugClassCode
  )
    return
  lookups.value[medicine.id] = {
    loading: true,
    result: null,
    selected: null,
    query: name,
    drugClassCode,
    error: '',
  }
  const state = lookups.value[medicine.id]!
  if (!searchGateway.available) {
    state.loading = false
    state.error = medicineSearchUnavailable
    return
  }
  try {
    const candidates = await searchGateway.search(drugClassCode, name)
    // 修改輸入、重新查詢、儲存或取消後，舊回應不能覆蓋目前資料。
    if (
      lookups.value[medicine.id] === state &&
      medicine.draftName.trim() === name &&
      medicine.isEditing &&
      classFor(medicine) === drugClassCode &&
      !disposed
    ) {
      if (
        !Array.isArray(candidates) ||
        candidates.some(
          (item) => !isMedicineCandidate(item) || item.drugClassCode !== drugClassCode,
        ) ||
        new Set(candidates.map((item) => item.id)).size !== candidates.length
      ) {
        state.error = '搜尋回應無法確認，請重試；未使用候選資料。'
        return
      }
      state.result = { candidates }
    }
  } catch (error) {
    if (
      lookups.value[medicine.id] === state &&
      medicine.draftName.trim() === name &&
      classFor(medicine) === drugClassCode &&
      medicine.isEditing &&
      !disposed
    )
      state.error = errorMessage(error)
  } finally {
    state.loading = false
  }
}

function selectDrug(medicine: MedicineRow, event: Event): void {
  const code = (event.target as HTMLSelectElement).value
  const candidate = lookups.value[medicine.id]?.result?.candidates.find((item) => item.id === code)
  const state = lookups.value[medicine.id]
  if (state && !candidate) state.selected = null
  if (
    !candidate ||
    !state ||
    state.query !== medicine.draftName.trim() ||
    candidate.drugClassCode !== classFor(medicine) ||
    medicine.isLocked ||
    !medicine.isEditing
  )
    return
  medicine.draftName = candidate.name
  state.query = candidate.name
  state.selected = { ...candidate }
}

function canReuseSavedReview(medicine: MedicineRow): boolean {
  return (
    hasValidMedicineReview(medicine) &&
    medicine.draftName.trim() === medicine.name.trim() &&
    classFor(medicine) === (medicine.selectedMedicine?.drugClassCode ?? '')
  )
}

function canSave(medicine: MedicineRow): boolean {
  if (medicine.isLocked || !medicine.isEditing) return false
  if (canReuseSavedReview(medicine)) return true
  if (classFor(medicine) === UNCERTAIN_DRUG_CLASS)
    return !!medicine.draftName.trim() && !medicine.isLocked && medicine.isEditing
  const state = lookups.value[medicine.id]
  return (
    !!state?.selected &&
    state.selected.name === medicine.draftName.trim() &&
    state.selected.drugClassCode === classFor(medicine) &&
    !state.loading &&
    !medicine.isLocked
  )
}

function saveMedicine(medicine: MedicineRow): void {
  if (!canSave(medicine)) {
    medicine.errorMessage =
      classFor(medicine) === UNCERTAIN_DRUG_CLASS
        ? '藥名不可空白'
        : '請先選擇用藥類別，並從正式搜尋結果選取藥品。'
    return
  }
  if (classFor(medicine) === UNCERTAIN_DRUG_CLASS)
    flow.saveMedicine(medicine, undefined, 'uncertain')
  else if (canReuseSavedReview(medicine)) flow.saveMedicine(medicine)
  else flow.saveMedicine(medicine, lookups.value[medicine.id]!.selected!)
  clearLookup(medicine)
}

function cancelEditing(medicine: MedicineRow): void {
  clearLookup(medicine)
  delete drugClasses.value[medicine.id]
  flow.cancelEditing(medicine)
}

// 此頁只讀取已保存的批次；返回上傳頁後會卸載，回來時重新建立預覽。
const previewUrls = new Map<File, string>()
const sourceImages = flow.drugBatches.flatMap((batch, batchIndex) =>
  batch.draft.source_images.map((image) => {
    const file = flow.findSourceFile(batch.draft.draft_id, image.image_id)
    if (file && !previewUrls.has(file)) {
      try {
        previewUrls.set(file, URL.createObjectURL(file))
      } catch {
        // 預覽失敗不影響藥名校對，也不以其他圖片替代。
      }
    }
    return {
      id: `source-${batch.draft.draft_id}-${image.image_id}`,
      batchNumber: batchIndex + 1,
      draftId: batch.draft.draft_id,
      imageId: image.image_id,
      fileName: file?.name,
      previewUrl: file ? previewUrls.get(file) : undefined,
    }
  }),
)

const reviewRows = computed(() =>
  medicines.value.map((medicine) => {
    const original =
      medicine.draftId !== null ? flow.findDraftRow(medicine.draftId, medicine.rowId) : undefined
    const source = original
      ? sourceImages.find(
          (image) =>
            image.draftId === medicine.draftId && image.imageId === original.source_image_id,
        )
      : undefined
    return { medicine, original, source }
  }),
)
const galleryImages = sourceImages.map((image) => ({
  id: image.id,
  label: `第 ${image.batchNumber} 批：${image.fileName ?? '來源圖片遺失'}`,
  src: image.previewUrl,
}))

onUnmounted(() => {
  disposed = true
  searchTimers.forEach(clearTimeout)
  lookups.value = {}
  previewUrls.forEach((url) => URL.revokeObjectURL(url))
})
onMounted(loadClasses)
</script>

<template>
  <main>
    <h1>核對你的藥品名稱</h1>
    <p>資料暫存在本機，返回上傳頁可繼續新增批次；重新整理後需要重新上傳。</p>
    <p v-if="!flow.drugBatches.length && !medicines.length" role="status">
      目前沒有藥品資料，請返回上傳處方箋圖片，或自行新增藥名。
    </p>
    <p><RouterLink to="/medicine-upload">返回藥圖片上傳／新增批次</RouterLink></p>

    <div class="review-layout">
      <section class="review-panel review-images" aria-labelledby="image-title">
        <h2 id="image-title">處方箋圖片預覽</h2>
        <ReviewImageGallery v-model:selected-id="selectedImageId" :images="galleryImages" />
      </section>

      <section class="review-panel review-fields" aria-labelledby="review-title">
        <h2 id="review-title">請確認資料是否正確</h2>
        <div v-if="medicines.length" class="review-progress">
          <p aria-live="polite">
            已完成本機校對 {{ confirmedCount }} / {{ medicines.length }} 項藥品
          </p>
          <progress :value="confirmedCount" :max="medicines.length" aria-label="藥品校對進度" />
        </div>
        <p>儲存只更新本機校對資料；鎖定表示由你確認，尚未送出評估。</p>
        <p>
          已辨識的藥品可直接鎖定，無須重新搜尋。未辨識的藥品或修改名稱後，請選擇用藥類別並搜尋候選藥品；也可選擇「其他／不確定」填寫名稱，儲存並鎖定後繼續。辨識原文仍會保留。
        </p>
        <p v-if="!searchGateway.available" role="status">{{ medicineSearchUnavailable }}</p>
        <p v-if="catalogLoading" role="status">正在載入用藥類別…</p>
        <p v-if="catalogError" role="alert">
          {{ catalogError }} <button type="button" @click="loadClasses">重試載入用藥類別</button>
        </p>
        <div v-if="medicines.length" class="bulk-controls">
          <button type="button" @click="setAllLocked(true)">一鍵鎖定</button>
          <button type="button" @click="setAllLocked(false)">全部解除鎖定</button>
        </div>
        <p role="status" aria-live="polite">{{ bulkMessage }}</p>
        <p v-if="medicines.length === 0">
          目前沒有藥品列；若照片未辨識出藥名，可以按「＋新增」人工輸入。
        </p>

        <ul v-else class="review-list">
          <li v-for="{ medicine, original, source } in reviewRows" :key="medicine.id">
            <p v-if="medicine.draftId === null">來源：手動新增（無來源圖片）</p>
            <template v-else>
              <p v-if="source">
                來源：<a :href="`#${source.id}`" @click="selectedImageId = source.id"
                  >第 {{ source.batchNumber }} 批：{{ source.fileName ?? '來源圖片遺失' }}</a
                >
              </p>
              <p v-else>來源圖片無法取得，請參考原始處方箋確認藥名。</p>
              <p>辨識原文：{{ original?.raw_name ?? '無法取得原文' }}</p>
            </template>

            <form v-if="medicine.isEditing" @submit.prevent="saveMedicine(medicine)">
              <label :for="`medicine-class-${medicine.id}`">用藥類別</label>
              <select
                :id="`medicine-class-${medicine.id}`"
                :value="classFor(medicine)"
                :disabled="catalogLoading"
                @change="changeClass(medicine, $event)"
              >
                <option value="">請先選擇用藥類別</option>
                <option
                  v-for="item in catalogClasses"
                  :key="item.drug_class_code"
                  :value="item.drug_class_code"
                >
                  {{ item.display_name_zh }} — {{ item.plain_description_zh }}
                </option>
                <option :value="UNCERTAIN_DRUG_CLASS">其他／不確定</option>
              </select>
              <label :for="`medicine-name-${medicine.id}`">藥品名稱</label>
              <input
                :id="`medicine-name-${medicine.id}`"
                v-model="medicine.draftName"
                type="text"
                :disabled="!classFor(medicine)"
                @input="inputChanged(medicine)"
                :aria-invalid="medicine.errorMessage ? 'true' : undefined"
                :aria-describedby="
                  medicine.errorMessage ? `medicine-error-${medicine.id}` : undefined
                "
              />
              <button
                v-if="classFor(medicine) !== UNCERTAIN_DRUG_CLASS"
                type="button"
                :disabled="
                  !searchGateway.available ||
                  !classFor(medicine) ||
                  !medicine.draftName.trim() ||
                  lookups[medicine.id]?.loading
                "
                @click="searchDrug(medicine)"
              >
                查詢候選藥名
              </button>
              <p v-if="lookups[medicine.id]?.loading" role="status">正在查詢藥名…</p>
              <p v-if="lookups[medicine.id]?.error" role="alert">
                {{ lookups[medicine.id]?.error }} 可按「查詢候選藥名」重試；不會自動確認輸入文字。
              </p>
              <template v-if="lookups[medicine.id]?.result">
                <label :for="`medicine-candidates-${medicine.id}`">候選藥品</label>
                <select
                  :id="`medicine-candidates-${medicine.id}`"
                  @change="selectDrug(medicine, $event)"
                >
                  <option value="">請選取實際藥品</option>
                  <option
                    v-for="candidate in lookups[medicine.id]?.result?.candidates"
                    :key="candidate.id"
                    :value="candidate.id"
                  >
                    {{ candidate.name
                    }}{{ candidate.specification ? `｜規格：${candidate.specification}` : ''
                    }}{{ candidate.licenseNumber ? `｜許可證：${candidate.licenseNumber}` : '' }}
                  </option>
                </select>
                <p v-if="!lookups[medicine.id]?.result?.candidates.length">
                  此類別找不到符合的候選藥品，請修改名稱或類別後重試；未找到不代表範圍外。
                </p>
                <p v-if="canSave(medicine)" role="status">已選取候選藥品，請確認藥品名稱後儲存。</p>
              </template>
              <p v-if="medicine.errorMessage" :id="`medicine-error-${medicine.id}`" role="alert">
                {{ medicine.errorMessage }}
              </p>
              <button type="submit" :disabled="!canSave(medicine)">儲存</button>
              <button type="button" @click="cancelEditing(medicine)">取消</button>
            </form>

            <div v-else class="review-row-content">
              <strong class="review-row-value">{{ medicine.name }}</strong>
              <p v-if="medicine.selectedMedicine?.specification">
                規格：{{ medicine.selectedMedicine.specification }}
              </p>
              <p v-if="medicine.selectedMedicine?.licenseNumber">
                許可證：{{ medicine.selectedMedicine.licenseNumber }}
              </p>
              <p v-if="medicine.reviewMode === 'uncertain'">
                其他／不確定：請核對名稱，鎖定後可繼續。
              </p>
              <p v-else-if="medicine.reviewMode === 'recognized'">已辨識，可直接鎖定。</p>
              <p v-else-if="!medicine.selectedMedicine">尚未辨識，請先編輯並完成藥品校對。</p>
              <p v-if="medicine.errorMessage" role="alert">{{ medicine.errorMessage }}</p>
              <div class="review-row-actions">
                <button
                  type="button"
                  :disabled="medicine.isLocked"
                  @click="flow.startEditing(medicine)"
                >
                  編輯
                </button>
                <label>
                  <input
                    type="checkbox"
                    :disabled="!hasValidMedicineReview(medicine)"
                    :checked="medicine.isLocked"
                    @change="flow.setLocked(medicine, ($event.target as HTMLInputElement).checked)"
                  />
                  鎖定變更
                </label>
              </div>
            </div>
          </li>
        </ul>

        <button type="button" @click="flow.addMedicine">＋新增</button>
        <div role="status" aria-live="polite">
          <p v-if="allConfirmed">本機藥品校對已完成，尚未送出評估。</p>
          <p v-else-if="medicines.length > 0">有未確認項目，麻煩請再檢查一次！</p>
        </div>
        <button class="primary-action" type="button" :disabled="!allConfirmed" @click="goNext">
          下一步：保健食品圖片上傳
        </button>
        <p v-if="!medicines.length">
          <RouterLink to="/supplement-upload">未提供用藥資料，前往保健食品圖片上傳</RouterLink>
        </p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.bulk-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
button,
select {
  min-height: 50px;
}
select {
  max-width: 100%;
}
</style>
