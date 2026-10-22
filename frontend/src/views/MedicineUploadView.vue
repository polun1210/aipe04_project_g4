<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { isUsableDraft, uploadDrugDraft, type DrugDraft } from '../api/drugs'
import { ApiError } from '../api/client'
import { useMedicineFlowStore } from '../stores/medicineFlow'

interface SelectedImage {
  id: number
  file: File
  previewUrl: string
  isLoaded: boolean
}

const MAX_IMAGES = 3
const MAX_FILE_BYTES = 3_000_000
const selectedImages = ref<SelectedImage[]>([])
const errorMessages = ref<string[]>([])
const router = useRouter()
const flow = useMedicineFlowStore()
const isUploading = ref(false)
const isNavigating = ref(false)
// 只在成功加入 Store 後設定，避免本機例外被當成成功。
const receivedDraft = shallowRef<DrugDraft | null>(null)
const nextBatchDialog = ref<HTMLDialogElement | null>(null)
const isBatchFrozen = computed(() => isUploading.value || receivedDraft.value !== null)
const validImageCount = computed(
  () => selectedImages.value.filter((image) => image.isLoaded).length,
)
let nextImageId = 1
const canUpload = computed(
  () =>
    !isBatchFrozen.value &&
    selectedImages.value.length > 0 &&
    selectedImages.value.length <= MAX_IMAGES &&
    validImageCount.value === selectedImages.value.length,
)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

async function startRecognition(): Promise<void> {
  if (!canUpload.value) return
  isUploading.value = true // 在第一個 await 前設置，阻止快速連點。
  errorMessages.value = []
  const files = selectedImages.value.map((image) => image.file)
  try {
    const draft: unknown = await uploadDrugDraft(files)
    if (!isUsableDraft(draft, files.length)) {
      errorMessages.value = [
        '後端回應缺少必要欄位或圖片來源不一致，無法使用草稿；未加入本機批次。圖片已保留，可手動重試。',
      ]
      return
    }
    flow.addDrugBatch(files, draft)
    receivedDraft.value = draft
    nextBatchDialog.value?.showModal()
  } catch (error: unknown) {
    const body: unknown = error instanceof ApiError ? error.body : null
    if (isRecord(body) && isRecord(body.error) && isText(body.error.message)) {
      errorMessages.value = [body.error.message]
      if (Array.isArray(body.error.details)) {
        errorMessages.value.push(...body.error.details.filter(isText))
      }
    } else {
      errorMessages.value = [
        '無法完成圖片辨識或本機保存，請確認後端與網路連線。圖片已保留，請稍後重試。',
      ]
    }
  } finally {
    isUploading.value = false
  }
}

function startNextBatch(): void {
  if (isUploading.value || isNavigating.value || !receivedDraft.value) return
  nextBatchDialog.value?.close()
  receivedDraft.value = null
  clearImages()
}

async function goToReview(): Promise<void> {
  if (isUploading.value || isNavigating.value || !receivedDraft.value) return
  isNavigating.value = true
  try {
    const failure = await router.push('/medicine-review')
    if (failure) errorMessages.value = ['尚未前往校對頁，批次仍保留，請再試一次。']
  } catch {
    errorMessages.value = ['無法前往校對頁，批次仍保留，請再試一次。']
  } finally {
    isNavigating.value = false
  }
}

onBeforeRouteLeave(() => {
  if (isUploading.value) {
    errorMessages.value = ['本批圖片正在辨識，請完成後再離開此頁。']
    return false
  }
})

function releasePreview(image: SelectedImage): void {
  URL.revokeObjectURL(image.previewUrl)
}

function removeImage(id: number): void {
  if (isBatchFrozen.value) return
  discardImage(id)
}

function discardImage(id: number): void {
  const index = selectedImages.value.findIndex((image) => image.id === id)
  const image = selectedImages.value[index]
  if (!image) return
  selectedImages.value.splice(index, 1)
  releasePreview(image)
}

function clearImages(): void {
  if (isBatchFrozen.value) return
  releaseAllPreviews()
  errorMessages.value = []
}

function releaseAllPreviews(): void {
  selectedImages.value.forEach(releasePreview)
  selectedImages.value = []
}

function isSameFile(first: File, second: File): boolean {
  return (
    first.name === second.name &&
    first.size === second.size &&
    first.type === second.type &&
    first.lastModified === second.lastModified
  )
}

function handleFileChange(event: Event): void {
  if (isBatchFrozen.value) return
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return

  const files = Array.from(input.files ?? [])
  // 取消選檔時保留原清單與訊息。
  if (files.length === 0) return

  // File 已保存在陣列中；清空原生欄位，讓重選同一檔案也能觸發 change。
  input.value = ''
  errorMessages.value = []
  const candidates: File[] = []
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      errorMessages.value.push(`${file.name}：檔案未標示為圖片類型，請選擇圖片檔。`)
      continue
    }
    if (file.size > MAX_FILE_BYTES) {
      errorMessages.value.push(`${file.name}：單張圖片不得超過 3,000,000 bytes（3 MB）。`)
      continue
    }
    if (
      selectedImages.value.some((image) => isSameFile(image.file, file)) ||
      candidates.some((candidate) => isSameFile(candidate, file))
    ) {
      errorMessages.value.push(
        `${file.name}：檔名、大小、類型及修改時間相同，已略過疑似重複圖片；未進行內容比對。`,
      )
      continue
    }
    candidates.push(file)
  }

  // 載入中的圖片也占名額；先檢查整次加入，超量時不改動原清單。
  if (selectedImages.value.length + candidates.length > MAX_IMAGES) {
    errorMessages.value.push('每批最多 3 張圖片；本次加入已取消，原有圖片保留。請減少選取數量。')
    return
  }

  for (const file of candidates) {
    try {
      const previewUrl = URL.createObjectURL(file)
      selectedImages.value.push({ id: nextImageId++, file, previewUrl, isLoaded: false })
    } catch {
      errorMessages.value.push(`${file.name}：本機預覽失敗，無法建立圖片預覽，請重新選擇圖片。`)
    }
  }
}

function findCurrentImage(event: Event, id: number): SelectedImage | undefined {
  const image = event.target
  const selected = selectedImages.value.find((item) => item.id === id)
  // 被移除或清空的舊圖片事件不能影響新清單。
  if (!(image instanceof HTMLImageElement) || image.src !== selected?.previewUrl) return
  return selected
}

function handlePreviewLoad(event: Event, id: number): void {
  const selected = findCurrentImage(event, id)
  if (!selected) return
  const image = event.target
  if (
    !(image instanceof HTMLImageElement) ||
    image.naturalWidth === 0 ||
    image.naturalHeight === 0
  ) {
    handlePreviewError(event, id)
    return
  }
  selected.isLoaded = true
}

function handlePreviewError(event: Event, id: number): void {
  const selected = findCurrentImage(event, id)
  if (!selected) return
  errorMessages.value.push(
    `${selected.file.name}：本機預覽失敗，瀏覽器無法讀取這張圖片，已移除，請選擇其他圖片。`,
  )
  discardImage(id)
}

onUnmounted(releaseAllPreviews)
</script>

<template>
  <main>
    <h1>藥圖片上傳</h1>
    <p id="upload-notice">選圖後按「開始辨識」會上傳圖片，辨識結果仍需由你逐筆校對。</p>

    <ul v-if="errorMessages.length" role="alert">
      <li v-for="(message, index) in errorMessages" :key="index">{{ message }}</li>
    </ul>
    <p>
      <label for="medicine-image">請上傳藥包圖片</label>
      <input
        id="medicine-image"
        type="file"
        accept="image/*"
        multiple
        :disabled="isBatchFrozen"
        aria-describedby="upload-notice upload-limits upload-privacy"
        @change="handleFileChange"
      />
    </p>
    <p id="upload-limits">每批最多 3 張；每張不超過 3,000,000 bytes（3 MB）。</p>
    <p role="status">
      目前已選擇 {{ selectedImages.length }} / 3 張，已完成載入驗證 {{ validImageCount }} 張。
    </p>
    <p v-if="selectedImages.length === 0">尚未選擇圖片。</p>

    <ul v-else>
      <li v-for="image in selectedImages" :key="image.id">
        <figure>
          <img
            :src="image.previewUrl"
            :alt="`${image.file.name} 的本機藥包圖片預覽`"
            @load="handlePreviewLoad($event, image.id)"
            @error="handlePreviewError($event, image.id)"
          />
          <figcaption>
            {{ image.file.name }}：{{
              image.isLoaded ? '本機預覽已載入' : '圖片載入驗證中，尚未視為有效圖片'
            }}
          </figcaption>
        </figure>
        <button
          type="button"
          :aria-label="`移除 ${image.file.name}`"
          :disabled="isBatchFrozen"
          @click="removeImage(image.id)"
        >
          移除
        </button>
      </li>
    </ul>
    <button
      type="button"
      :disabled="isBatchFrozen || selectedImages.length === 0"
      @click="clearImages"
    >
      清空目前圖片
    </button>

    <p id="upload-privacy">
      圖片上傳提醒：藥包照片可能包含姓名、醫院名稱等個人資訊。辨識時，照片會透過 OpenRouter 轉送至
      Google 的辨識服務。建議上傳前先遮住姓名等不必要的個人資訊。
    </p>
    <p>
      <button type="button" :disabled="!canUpload" @click="startRecognition">開始辨識</button>
    </p>
    <p v-if="isUploading" role="status">圖片上傳與辨識處理中</p>
    <p v-else-if="!receivedDraft">請等待所有圖片完成載入驗證後開始辨識。失敗時不會自動重送。</p>

    <p v-if="flow.drugBatches.length && !receivedDraft">
      已保存 {{ flow.drugBatches.length }} 批。
      <RouterLink to="/medicine-review">返回藥人工校對</RouterLink>
    </p>

    <dialog ref="nextBatchDialog" aria-labelledby="next-batch-title" @cancel.prevent>
      <template v-if="receivedDraft">
        <h2 id="next-batch-title">是否還有其他藥包？</h2>
        <p role="status">草稿已保存在本機，共 {{ flow.drugBatches.length }} 批，請繼續校對。</p>
        <p v-if="receivedDraft.extraction_meta.ocr_version === 'stub'" role="status">
          目前是測試資料，不是實際辨識結果
        </p>
        <ul v-if="errorMessages.length" role="alert">
          <li v-for="(message, index) in errorMessages" :key="index">{{ message }}</li>
        </ul>
        <button type="button" :disabled="isUploading || isNavigating" @click="startNextBatch">
          有
        </button>
        <button type="button" :disabled="isUploading || isNavigating" @click="goToReview">
          沒有
        </button>
      </template>
    </dialog>

    <p>
      <button
        type="button"
        :disabled="
          isBatchFrozen || isNavigating || (flow.medicines.length > 0 && !flow.allConfirmed)
        "
        @click="router.push('/supplement-upload')"
      >
        前往辨識保健食品
      </button>
    </p>
    <p>未提供用藥資料時，可直接前往辨識保健食品。若已加入藥品，請先完成校對。</p>
  </main>
</template>
