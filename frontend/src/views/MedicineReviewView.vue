<script setup lang="ts">
import { computed, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useMedicineFlowStore } from '../stores/medicineFlow'

const flow = useMedicineFlowStore()
const { medicines, allConfirmed } = storeToRefs(flow)

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

          <form v-if="medicine.isEditing" @submit.prevent="flow.saveMedicine(medicine)">
            <label :for="`medicine-name-${medicine.id}`">藥名</label>
            <input
              :id="`medicine-name-${medicine.id}`"
              v-model="medicine.draftName"
              type="text"
              :aria-invalid="medicine.errorMessage ? 'true' : undefined"
              :aria-describedby="
                medicine.errorMessage ? `medicine-error-${medicine.id}` : undefined
              "
            />
            <p v-if="medicine.errorMessage" :id="`medicine-error-${medicine.id}`" role="alert">
              {{ medicine.errorMessage }}
            </p>
            <button type="submit">儲存</button>
            <button type="button" @click="flow.cancelEditing(medicine)">取消</button>
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
