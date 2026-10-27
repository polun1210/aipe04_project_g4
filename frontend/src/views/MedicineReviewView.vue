<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useMedicineFlowStore, type MedicineRow } from '../stores/medicineFlow'
import { lookupDrug, type DrugLookupResponse } from '../api/drugs'
import { errorMessage } from '../api/client'

const flow = useMedicineFlowStore()
const { medicines, allConfirmed } = storeToRefs(flow)
const bulkMessage = ref('')
const lookups = ref<
  Record<
    string,
    {
      loading: boolean
      result: DrugLookupResponse | null
      error: string
    }
  >
>({})

function setAllLocked(locked: boolean): void {
  const skipped = flow.setAllLocked(locked)
  bulkMessage.value = skipped
    ? `有 ${skipped} 筆無法鎖定：請確認藥名非空白，並先儲存或取消編輯，再按「一鍵鎖定」。其他可鎖定的藥品已鎖定。`
    : locked
      ? '全部藥品已鎖定，尚未送出評估。'
      : '全部藥品已解除鎖定。'
}

function clearLookup(medicine: MedicineRow): void {
  delete lookups.value[medicine.id]
}

async function searchDrug(medicine: MedicineRow): Promise<void> {
  const name = medicine.draftName.trim()
  if (!name || !medicine.isEditing || medicine.isLocked) return
  lookups.value[medicine.id] = { loading: true, result: null, error: '' }
  const state = lookups.value[medicine.id]!
  try {
    const result = await lookupDrug(name)
    // 修改輸入、重新查詢、儲存或取消後，舊回應不能覆蓋目前資料。
    if (
      lookups.value[medicine.id] === state &&
      medicine.draftName.trim() === name &&
      medicine.isEditing
    ) {
      state.result = result
    }
  } catch (error) {
    if (lookups.value[medicine.id] === state) state.error = errorMessage(error)
  } finally {
    state.loading = false
  }
}

function selectDrug(medicine: MedicineRow, event: Event): void {
  const code = (event.target as HTMLSelectElement).value
  const candidate = lookups.value[medicine.id]?.result?.candidates.find(
    (item) => item.active_ingredient_code === code,
  )
  if (!candidate || medicine.isLocked || !medicine.isEditing) return
  // 使用目錄可精確對照的中文名；不修改辨識原文，也不傳前端對照結果。
  medicine.draftName = candidate.display_name_zh
  clearLookup(medicine)
  void searchDrug(medicine)
}

function saveMedicine(medicine: MedicineRow): void {
  flow.saveMedicine(medicine)
  clearLookup(medicine)
}

function cancelEditing(medicine: MedicineRow): void {
  clearLookup(medicine)
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

onUnmounted(() => {
  previewUrls.forEach((url) => URL.revokeObjectURL(url))
})
</script>

<template>
  <main>
    <h1>藥人工校對</h1>
    <p>資料暫存在本機，返回上傳頁可繼續新增批次；重新整理後需要重新上傳。</p>
    <p v-if="!flow.drugBatches.length && !medicines.length" role="status">
      目前沒有藥品資料，請返回上傳藥包圖片，或自行新增藥名。
    </p>
    <p><RouterLink to="/medicine-upload">返回藥圖片上傳／新增批次</RouterLink></p>

    <section aria-labelledby="image-title">
      <h2 id="image-title">藥包圖片預覽</h2>
      <p v-if="!sourceImages.length">目前沒有可預覽的藥包圖片。</p>
      <figure v-for="image in sourceImages" :id="image.id" :key="image.id">
        <img
          v-if="image.previewUrl"
          :src="image.previewUrl"
          :alt="`第 ${image.batchNumber} 批：${image.fileName} 的藥包圖片`"
          width="320"
        />
        <p v-else>無法預覽此來源圖片，請參考原始藥包確認藥名。</p>
        <figcaption>
          第 {{ image.batchNumber }} 批：{{ image.fileName ?? '來源圖片遺失' }}
        </figcaption>
      </figure>
    </section>

    <section aria-labelledby="review-title">
      <h2 id="review-title">請確認資料是否正確</h2>
      <p>儲存只更新本機校對資料；鎖定表示由你確認，尚未送出評估。</p>
      <p>
        藥名可手動輸入或查詢候選藥名；候選來自後端目前的藥品目錄，未列出不代表範圍外。送出評估時由後端決定對照結果。
      </p>
      <div v-if="medicines.length" class="bulk-controls">
        <button type="button" @click="setAllLocked(true)">一鍵鎖定</button>
        <button type="button" @click="setAllLocked(false)">全部解除鎖定</button>
      </div>
      <p role="status" aria-live="polite">{{ bulkMessage }}</p>
      <p v-if="medicines.length === 0">
        目前沒有藥品列；若照片未辨識出藥名，可以按「＋新增」人工輸入。
      </p>

      <ul v-else>
        <li v-for="{ medicine, original, source } in reviewRows" :key="medicine.id">
          <p v-if="medicine.draftId === null">來源：手動新增（無來源圖片）</p>
          <template v-else>
            <p v-if="source">
              來源：<a :href="`#${source.id}`"
                >第 {{ source.batchNumber }} 批：{{ source.fileName ?? '來源圖片遺失' }}</a
              >
            </p>
            <p v-else>來源圖片無法取得，請參考原始藥包確認藥名。</p>
            <p>辨識原文：{{ original?.raw_name ?? '無法取得原文' }}</p>
          </template>

          <form v-if="medicine.isEditing" @submit.prevent="saveMedicine(medicine)">
            <label :for="`medicine-name-${medicine.id}`">藥名</label>
            <input
              :id="`medicine-name-${medicine.id}`"
              v-model="medicine.draftName"
              type="text"
              @input="clearLookup(medicine)"
              :aria-invalid="medicine.errorMessage ? 'true' : undefined"
              :aria-describedby="
                medicine.errorMessage ? `medicine-error-${medicine.id}` : undefined
              "
            />
            <button
              type="button"
              :disabled="!medicine.draftName.trim() || lookups[medicine.id]?.loading"
              @click="searchDrug(medicine)"
            >
              查詢候選藥名
            </button>
            <p v-if="lookups[medicine.id]?.loading" role="status">正在查詢藥名…</p>
            <p v-if="lookups[medicine.id]?.error" role="alert">
              {{ lookups[medicine.id]?.error }} 請重新查詢，或保留手動輸入的藥名。
            </p>
            <template v-if="lookups[medicine.id]?.result">
              <label :for="`medicine-candidates-${medicine.id}`">候選藥名（最多 10 筆）</label>
              <select
                :id="`medicine-candidates-${medicine.id}`"
                @change="selectDrug(medicine, $event)"
              >
                <option value="">請選擇藥名，或繼續手動輸入</option>
                <option
                  v-for="candidate in lookups[medicine.id]?.result?.candidates"
                  :key="candidate.active_ingredient_code"
                  :value="candidate.active_ingredient_code"
                >
                  {{ candidate.display_name_zh }}／{{ candidate.english_name }}（符合名稱：{{
                    candidate.matched_name
                  }}）
                </option>
              </select>
              <p v-if="!lookups[medicine.id]?.result?.candidates.length">
                目前目錄沒有候選藥名，可保留手動輸入；不代表此藥為範圍外。
              </p>
              <p>
                輸入名稱對照：{{
                  lookups[medicine.id]?.result?.mapped.scope_status === 'in_scope'
                    ? '範圍內'
                    : lookups[medicine.id]?.result?.mapped.scope_status === 'out_of_scope'
                      ? '範圍外'
                      : '無法確認'
                }}。若藥名未修改，評估仍沿用後端草稿的辨識對照。
              </p>
            </template>
            <p v-if="medicine.errorMessage" :id="`medicine-error-${medicine.id}`" role="alert">
              {{ medicine.errorMessage }}
            </p>
            <button type="submit">儲存</button>
            <button type="button" @click="cancelEditing(medicine)">取消</button>
          </form>

          <div v-else>
            <span>{{ medicine.name }}</span>
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
                :checked="medicine.isLocked"
                @change="flow.setLocked(medicine, ($event.target as HTMLInputElement).checked)"
              />
              鎖定變更
            </label>
          </div>
        </li>
      </ul>

      <button type="button" @click="flow.addMedicine">＋新增</button>

      <div role="status" aria-live="polite">
        <p v-if="allConfirmed">本機藥品資料已確認完成，尚未送出評估。</p>
        <p v-else-if="medicines.length > 0">有未確認項目，麻煩請再檢查一次！</p>
      </div>
      <button type="button" :disabled="!allConfirmed" @click="$router.push('/supplement-upload')">
        下一步：保健食品圖片上傳
      </button>
      <p v-if="!medicines.length">
        <RouterLink to="/supplement-upload">未提供用藥資料，前往保健食品圖片上傳</RouterLink>
      </p>
    </section>
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
  min-height: 44px;
}
select {
  max-width: 100%;
}
</style>
