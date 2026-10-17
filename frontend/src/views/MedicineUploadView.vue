<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const errorMessage = ref('')

function releasePreview(): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function handleFileChange(event: Event): void {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return

  const file = input.files?.[0]
  // 沒有新檔案時保留原選擇，例如使用者取消選檔。
  if (!file) return

  // File 已保存在變數中；清空原生欄位，讓下次重選同一檔案也能觸發 change。
  input.value = ''
  releasePreview()
  selectedFile.value = null
  errorMessage.value = ''

  if (!file.type.startsWith('image/')) {
    errorMessage.value = '本機選檔失敗：檔案未標示為圖片類型，請選擇圖片檔。'
    return
  }

  selectedFile.value = file
  try {
    previewUrl.value = URL.createObjectURL(file)
  } catch {
    errorMessage.value = '本機預覽失敗：無法建立圖片預覽，請重新選擇圖片。'
  }
}

function handlePreviewError(event: Event): void {
  const image = event.target
  // 忽略已被替換的舊圖片事件，避免清除新圖片的網址。
  if (!(image instanceof HTMLImageElement) || image.src !== previewUrl.value) return

  releasePreview()
  errorMessage.value = '本機預覽失敗：瀏覽器無法讀取這張圖片，請選擇其他圖片。'
}

onUnmounted(releasePreview)
</script>

<template>
  <main>
    <h1>藥圖片上傳</h1>
    <p id="upload-notice">目前僅提供本機選圖與預覽，圖片不會上傳，也不會進行辨識。</p>

    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <p>
      <label for="medicine-image">請上傳藥包圖片</label>
      <input
        id="medicine-image"
        type="file"
        accept="image/*"
        aria-describedby="upload-notice"
        @change="handleFileChange"
      />
    </p>
    <p>目前檔案：{{ selectedFile ? selectedFile.name : '尚未選擇圖片' }}</p>

    <figure v-if="previewUrl">
      <img
        :key="previewUrl"
        :src="previewUrl"
        alt="目前選取的藥包圖片預覽"
        @error="handlePreviewError"
      />
      <figcaption>本機圖片預覽，尚未上傳或辨識。</figcaption>
    </figure>

    <p>
      <button type="button" disabled>開始辨識（尚未開放）</button>
    </p>
    <p>目前沒有可用的圖片上傳與藥包辨識 API，因此無法開始辨識。</p>

    <p>
      <button type="button" disabled>前往辨識保健食品（頁面尚未建立）</button>
    </p>
    <p>沒有使用慢性病藥或腸胃藥時，未來可直接前往辨識保健食品；目前該頁尚未建立。</p>
  </main>
</template>
