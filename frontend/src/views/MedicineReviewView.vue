<script setup lang="ts">
import { computed, ref } from 'vue'

interface MedicineRow {
  id: number
  name: string
  draftName: string
  isNew: boolean
  isEditing: boolean
  isLocked: boolean
  errorMessage: string
}

const medicines = ref<MedicineRow[]>([])
let nextId = 1

const allConfirmed = computed(
  () =>
    medicines.value.length > 0 &&
    medicines.value.every(
      (medicine) => medicine.name.trim() !== '' && !medicine.isEditing && medicine.isLocked,
    ),
)

function addMedicine(): void {
  medicines.value.push({
    id: nextId++,
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

function removeMedicine(id: number): void {
  medicines.value = medicines.value.filter((medicine) => medicine.id !== id)
}

function saveMedicine(medicine: MedicineRow): void {
  if (medicine.isLocked || !medicine.isEditing) return
  const name = medicine.draftName.trim()

  if (!name) {
    if (medicine.isNew) {
      removeMedicine(medicine.id)
    } else {
      medicine.errorMessage = '藥名不可空白'
    }
    return
  }

  medicine.name = name
  medicine.draftName = name
  medicine.isNew = false
  medicine.isEditing = false
  medicine.isLocked = false
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
</script>

<template>
  <main>
    <h1>藥人工校對</h1>
    <p>目前沒有辨識資料，可自行新增藥名。資料只暫存在本頁，重新整理或離開後不會保留。</p>

    <section aria-labelledby="image-title">
      <h2 id="image-title">藥包圖片預覽</h2>
      <p>目前沒有可預覽的藥包圖片，尚未從上傳頁取得圖片。</p>
    </section>

    <section aria-labelledby="review-title">
      <h2 id="review-title">請確認資料是否正確</h2>
      <p>儲存只更新本頁資料；鎖定表示由你確認，不代表後端已驗證或儲存。</p>
      <p v-if="medicines.length === 0">目前沒有藥品，請新增一筆。</p>

      <ul v-else>
        <li v-for="medicine in medicines" :key="medicine.id">
          <form v-if="medicine.isEditing" @submit.prevent="saveMedicine(medicine)">
            <label :for="`medicine-name-${medicine.id}`">藥名</label>
            <input
              :id="`medicine-name-${medicine.id}`"
              v-model="medicine.draftName"
              type="text"
              :aria-invalid="medicine.errorMessage ? 'true' : undefined"
              :aria-describedby="medicine.errorMessage ? `medicine-error-${medicine.id}` : undefined"
            />
            <p>候選藥名功能尚未開放。</p>
            <p
              v-if="medicine.errorMessage"
              :id="`medicine-error-${medicine.id}`"
              role="alert"
            >
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
              @click="startEditing(medicine)"
            >
              編輯
            </button>
            <label>
              <input v-model="medicine.isLocked" type="checkbox" />
              鎖定變更
            </label>
          </div>
        </li>
      </ul>

      <button type="button" @click="addMedicine">＋新增</button>

      <div role="status" aria-live="polite">
        <p v-if="allConfirmed">本機藥品資料已確認，尚未經後端驗證或儲存。</p>
        <p v-else-if="medicines.length > 0">有未確認項目，麻煩請再檢查一次！</p>
      </div>
      <button type="button" disabled>下一步（尚未開放）</button>
      <p>保健食品圖片上傳頁尚未建立，藥品資料的跨頁交接也尚未完成。</p>
    </section>
  </main>
</template>
