<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { errorMessage } from '../api/client'
import {
  isTestExtraction,
  isUsableSupplementDraft,
  uploadSupplementDraft,
} from '../api/supplements'
import { useMedicineFlowStore } from '../stores/medicineFlow'
import { useSupplementFlowStore } from '../stores/supplementFlow'

type Kind = 'ingredients' | 'nutrition'
interface ImageSelection {
  id: number
  file: File
  url: string
  kind: Kind
  loaded: boolean
}
const router = useRouter()
const medicine = useMedicineFlowStore()
const flow = useSupplementFlowStore()
const category = ref('')
const productName = ref('')
const showRequiredErrors = ref(false)
const categoryError = computed(() => {
  if (!category.value.trim()) return '請選擇或輸入保健食品種類。'
  return category.value.trim().length > 30 ? '保健食品種類最多 30 字。' : ''
})
const nameError = computed(() =>
  productName.value.trim() ? '' : '請填寫保健食品名稱，不能只有空白。',
)
const images = ref<ImageSelection[]>([])
const error = ref('')
const busy = ref(false)
const received = ref(false)
const stub = ref(false)
const dialog = ref<HTMLDialogElement | null>(null)
let nextId = 1
const medicineReady = computed(() => !medicine.medicines.length || medicine.allConfirmed)
const frozen = computed(() => busy.value || received.value)
const canUpload = computed(
  () =>
    !frozen.value &&
    medicineReady.value &&
    images.value.length > 0 &&
    images.value.every((image) => image.loaded),
)
function remove(id: number) {
  if (frozen.value) return
  const image = images.value.find((item) => item.id === id)
  if (image) URL.revokeObjectURL(image.url)
  images.value = images.value.filter((item) => item.id !== id)
}
function releaseImages() {
  images.value.forEach((image) => URL.revokeObjectURL(image.url))
  images.value = []
}
function selectFiles(event: Event, kind: Kind) {
  const input = event.target as HTMLInputElement
  if (frozen.value) return
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  error.value = ''
  for (const file of files) {
    if (!file.type.startsWith('image/') || file.size > 3_000_000) {
      error.value = '請選擇圖片，每張不得超過 3 MB。'
      continue
    }
    if (images.value.length >= 3) {
      error.value = '每批成分表與營養標示合計最多 3 張。'
      break
    }
    if (
      images.value.some(
        (image) =>
          image.kind === kind &&
          image.file.name === file.name &&
          image.file.size === file.size &&
          image.file.lastModified === file.lastModified,
      )
    ) {
      error.value = '已略過疑似重複圖片。'
      continue
    }
    try {
      images.value.push({ id: nextId++, file, kind, url: URL.createObjectURL(file), loaded: false })
    } catch {
      error.value = '無法建立圖片預覽，請重新選擇圖片。'
    }
  }
}
function previewFailed(id: number) {
  remove(id)
  error.value = '圖片無法讀取，已移除，請重新選擇。'
}
async function recognize() {
  if (!canUpload.value) return
  showRequiredErrors.value = true
  if (categoryError.value || nameError.value) return
  const name = productName.value.trim()
  busy.value = true
  error.value = ''
  // 與後端一致：先成分表，再營養標示；img-01 對應第一個送出的 File。
  const ingredients = images.value
    .filter((image) => image.kind === 'ingredients')
    .map((image) => image.file)
  const nutrition = images.value
    .filter((image) => image.kind === 'nutrition')
    .map((image) => image.file)
  try {
    const draft: unknown = await uploadSupplementDraft(ingredients, nutrition, category.value)
    if (!isUsableSupplementDraft(draft, ingredients.length + nutrition.length)) {
      error.value = '後端回應缺少必要資料或圖片來源不一致；圖片已保留，請重試。'
      return
    }
    flow.addBatch([...ingredients, ...nutrition], draft, name)
    received.value = true
    stub.value = isTestExtraction(draft.extraction_meta.ocr_version)
    dialog.value?.showModal()
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    busy.value = false
  }
}
function nextBatch() {
  dialog.value?.close()
  received.value = false
  stub.value = false
  releaseImages()
  category.value = ''
  productName.value = ''
  showRequiredErrors.value = false
  error.value = ''
}
async function review() {
  error.value = ''
  try {
    await router.push('/supplement-review')
  } catch {
    error.value = '無法前往校對頁，已保存的批次仍保留。'
  }
}
onBeforeRouteLeave(() => {
  if (busy.value) {
    error.value = '圖片正在辨識，請完成後再離開。'
    return false
  }
})
onUnmounted(releaseImages)
</script>

<template>
  <main class="supplement-upload">
    <h1>保健食品圖片上傳</h1>
    <p>每批代表一罐產品，可上傳成分表或營養標示，辨識結果仍需逐筆校對。</p>
    <p v-if="!medicineReady" role="alert">藥品尚未全部確認，請先完成藥品校對。</p>
    <p><RouterLink to="/medicine-review">返回藥人工校對</RouterLink></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <form novalidate @submit.prevent="recognize">
      <fieldset :disabled="frozen || !medicineReady">
        <legend>本罐產品的圖片</legend>
        <p>
          <label for="supplement-category">保健食品種類（必填）</label>
          <input
            id="supplement-category"
            v-model="category"
            list="supplement-categories"
            maxlength="30"
            required
            :aria-invalid="showRequiredErrors && categoryError ? 'true' : undefined"
            :aria-describedby="showRequiredErrors && categoryError ? 'category-error' : undefined"
          />
          <datalist id="supplement-categories">
            <option value="綜合維他命" />
            <option value="魚油" />
            <option value="鈣" />
            <option value="紅麴" />
            <option value="葡萄糖胺" />
          </datalist>
        </p>
        <p
          v-if="showRequiredErrors && categoryError"
          id="category-error"
          class="field-error"
          role="alert"
        >
          {{ categoryError }}
        </p>
        <p>可從建議種類選取或自行輸入，最多 30 字；種類不影響辨識或評估。</p>
        <p>
          <label for="supplement-name">保健食品名稱（必填）</label>
          <input
            id="supplement-name"
            v-model="productName"
            required
            :aria-invalid="showRequiredErrors && nameError ? 'true' : undefined"
            :aria-describedby="showRequiredErrors && nameError ? 'name-error' : undefined"
          />
        </p>
        <p v-if="showRequiredErrors && nameError" id="name-error" class="field-error" role="alert">
          {{ nameError }}
        </p>
        <p>請填寫產品包裝上的名稱，辨識後仍可在人工校對頁修改。</p>
        <p>
          <label for="ingredient-images">成分表</label>
          <input
            id="ingredient-images"
            type="file"
            accept="image/*"
            multiple
            @change="selectFiles($event, 'ingredients')"
          />
        </p>
        <p>
          <label for="nutrition-images">營養標示</label>
          <input
            id="nutrition-images"
            type="file"
            accept="image/*"
            multiple
            @change="selectFiles($event, 'nutrition')"
          />
        </p>
        <p>合計 1 至 3 張，每張不得超過 3 MB。已選擇 {{ images.length }} 張。</p>
        <ul>
          <li v-for="image in images" :key="image.id">
            <img
              :src="image.url"
              :alt="image.file.name"
              width="240"
              @load="image.loaded = true"
              @error="previewFailed(image.id)"
            />
            <p>{{ image.kind === 'ingredients' ? '成分表' : '營養標示' }}：{{ image.file.name }}</p>
            <button type="button" @click="remove(image.id)">移除 {{ image.file.name }}</button>
          </li>
        </ul>
        <p>
          圖片上傳提醒：照片可能包含姓名等個人資訊。辨識時，照片會透過 OpenRouter 轉送至 Google
          的辨識服務。建議上傳前先遮住姓名等不必要的個人資訊。
        </p>
        <button type="submit" :disabled="!canUpload">開始辨識</button>
      </fieldset>
    </form>
    <p v-if="busy" role="status">圖片上傳與辨識處理中…</p>
    <p v-if="flow.products.length && !received">
      <RouterLink to="/supplement-review"
        >前往保健食品人工校對（已保存 {{ flow.products.length }} 罐）</RouterLink
      >
    </p>
    <dialog ref="dialog" aria-labelledby="more-supplements" @cancel.prevent>
      <h2 id="more-supplements">是否還有其他保健食品？</h2>
      <p>已保存 {{ flow.products.length }} 罐，請繼續校對。</p>
      <p v-if="stub" role="status">目前是測試資料，不是實際辨識結果</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="button" :disabled="busy" @click="nextBatch">有</button>
      <button type="button" :disabled="busy" @click="review">沒有</button>
    </dialog>
  </main>
</template>

<style scoped>
.supplement-upload {
  font-size: 18px;
  line-height: 1.6;
}

button,
input {
  font: inherit;
}

button,
input::file-selector-button {
  min-height: 50px;
  padding: 0.5rem 1rem;
  font: inherit;
}

.field-error {
  color: #a21616;
  font-weight: 600;
}
</style>
