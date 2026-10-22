<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { getCatalog, type Ingredient } from '../api/catalog'
import { errorMessage } from '../api/client'
import {
  createProduct,
  doseAmounts,
  doseLabels,
  isTestExtraction,
  unitOptions,
} from '../api/supplements'
import { useMedicineFlowStore } from '../stores/medicineFlow'
import {
  productReady,
  submissionFor,
  useSupplementFlowStore,
  type NutrientRow,
} from '../stores/supplementFlow'

const flow = useSupplementFlowStore()
const medicine = useMedicineFlowStore()
const ingredients = ref<Ingredient[]>([])
const catalogBusy = ref(false)
const error = ref('')
const busy = ref(false)
const stage = ref('')
const urls = new Map<File, string>()
const previews = flow.products.flatMap((product) =>
  product.draft.source_images.map((image) => {
    const index = product.files.findIndex(
      (_, i) => image.image_id === `img-${String(i + 1).padStart(2, '0')}`,
    )
    const file = product.files[index]
    if (file && !urls.has(file)) {
      try {
        urls.set(file, URL.createObjectURL(file))
      } catch {
        /* 仍可依原始標示校對。 */
      }
    }
    return {
      productId: product.id,
      imageId: image.image_id,
      name: file?.name,
      url: file ? urls.get(file) : undefined,
      id: `supplement-${product.id}-${image.image_id}`,
    }
  }),
)
const canSubmit = computed(
  () =>
    !busy.value &&
    !catalogBusy.value &&
    ingredients.value.length > 0 &&
    flow.products.length > 0 &&
    (!medicine.medicines.length || medicine.allConfirmed) &&
    flow.products.every((product) => productReady(product, ingredients.value)),
)
const allSaved = computed(() => flow.products.length > 0 && flow.products.every(product => product.savedProductId && product.savedPayload === JSON.stringify(submissionFor(product))))
async function loadCatalog() {
  catalogBusy.value = true
  error.value = ''
  try {
    ingredients.value = (await getCatalog()).ingredients
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    catalogBusy.value = false
  }
}
function chooseNutrient(row: NutrientRow) {
  const item = ingredients.value.find((ingredient) => ingredient.code === row.edit.choice)
  if (row.edit.choice !== row.value.choice) {
    row.edit.form = ''
    row.edit.elemental = null
  }
  if (item && (!row.edit.unit || !item.accepted_units.includes(row.edit.unit)))
    row.edit.unit = item.standard_unit ?? ''
}
function nameFor(choice: string) {
  return (
    ingredients.value.find((item) => item.code === choice)?.display_name_zh ??
    { out_of_scope: '不在評估範圍', unresolved: '無法確認' }[choice] ??
    '請選擇營養素'
  )
}
async function submit() {
  if (!canSubmit.value) return
  busy.value = true
  error.value = ''
  try {
    const ids: string[] = []
    for (const [index, product] of flow.products.entries()) {
      stage.value = `正在保存第 ${index + 1} 罐…`
      const payload = submissionFor(product)
      const serialized = JSON.stringify(payload)
      // 前一次已保存且內容相同的產品可沿用編號，避免後續 API 失敗時重建。
      if (!product.savedProductId || product.savedPayload !== serialized) {
        const result = await createProduct(payload)
        product.savedProductId = result.product_id
        product.savedPayload = serialized
      }
      ids.push(product.savedProductId)
    }
    stage.value = `已保存 ${ids.length} 罐`
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    busy.value = false
    stage.value = ''
  }
}
onMounted(loadCatalog)
onUnmounted(() => urls.forEach((url) => URL.revokeObjectURL(url)))
onBeforeRouteLeave(() => {
  // 保存產品期間避免離開，保留錯誤後重試的入口。
  if (busy.value) return false
})
</script>

<template>
  <main>
    <h1>保健食品人工校對</h1>
    <p>資料暫存在本機，重新整理後需要重新上傳。請依原始標示確認每份量及成分。</p>
    <p>保存只建立後端產品資料，尚未送出評估。</p>
    <p><RouterLink to="/supplement-upload">返回上傳／新增其他保健食品</RouterLink></p>
    <p v-if="!flow.products.length">目前沒有保健食品資料，請先上傳圖片。</p>
    <p v-if="medicine.medicines.length && !medicine.allConfirmed" role="alert">
      藥品尚未全部確認。<RouterLink to="/medicine-review">返回藥品校對</RouterLink>
    </p>
    <p v-if="catalogBusy" role="status">正在載入營養素選項…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="!ingredients.length && !catalogBusy" type="button" @click="loadCatalog">
      重新載入營養素選項
    </button>

    <form @submit.prevent="submit">
      <fieldset :disabled="busy || catalogBusy || !ingredients.length">
        <legend>確認保健食品與實際服用方式</legend>
        <section
          v-for="(product, index) in flow.products"
          :key="product.id"
          :aria-labelledby="`product-${product.id}`"
        >
          <h2 :id="`product-${product.id}`">{{ product.name || `保健食品 ${index + 1}` }}</h2>
          <p v-if="isTestExtraction(product.draft.extraction_meta.ocr_version)">
            目前是測試資料，不是實際辨識結果
          </p>
          <figure
            v-for="image in previews.filter((item) => item.productId === product.id)"
            :id="image.id"
            :key="image.id"
          >
            <img v-if="image.url" :src="image.url" :alt="image.name" width="280" />
            <p v-else>無法取得此來源圖片，請參考原始標示。</p>
            <figcaption>{{ image.name ?? '來源圖片遺失' }}</figcaption>
          </figure>
          <p>
            <label :for="`name-${product.id}`">產品名稱</label>
            <input :id="`name-${product.id}`" v-model="product.name" />
          </p>
          <p>
            <label :for="`serving-${product.id}`">每份量（幾錠／粒／mL 等）</label>
            <input
              :id="`serving-${product.id}`"
              v-model.number="product.servingSize"
              type="number"
              min="0"
              step="any"
              required
            />
          </p>
          <p>
            <label :for="`dose-${product.id}`">劑型／每份量單位</label>
            <select :id="`dose-${product.id}`" v-model="product.doseUnit" required>
              <option value="" disabled>請選擇</option>
              <option v-for="(label, code) in doseLabels" :key="code" :value="code">
                {{ label }}
              </option>
            </select>
          </p>
          <h3>營養素與每份含量</h3>
          <p v-if="!product.rows.length">目前沒有成分列，請按「＋新增營養素」。</p>
          <ul>
            <li v-for="row in product.rows" :key="row.id">
              <p v-if="row.rawName !== null">
                辨識原文：{{ row.rawName }}
                <a
                  v-if="
                    previews.some(
                      (image) =>
                        image.productId === product.id && image.imageId === row.sourceImageId,
                    )
                  "
                  :href="`#supplement-${product.id}-${row.sourceImageId}`"
                  >查看來源圖片</a
                >
              </p>
              <p v-else>手動新增（無來源圖片）</p>
              <p
                v-if="
                  product.draft.nutrients.some(
                    (item) => item.row_id === row.rowId && item.requires_user_input,
                  )
                "
              >
                此列辨識有不確定之處，請核對原始標示。
              </p>
              <template v-if="row.editing">
                <p>
                  <label :for="`nutrient-${row.id}`">營養素名稱／評估範圍</label>
                  <select
                    :id="`nutrient-${row.id}`"
                    v-model="row.edit.choice"
                    @change="chooseNutrient(row)"
                  >
                    <option value="">請選擇</option>
                    <option v-for="item in ingredients" :key="item.code" :value="item.code">
                      {{ item.display_name_zh }}
                    </option>
                    <option value="out_of_scope">不在評估範圍</option>
                    <option value="unresolved">無法確認</option>
                  </select>
                </p>
                <p>
                  <label :for="`amount-${row.id}`">每份含量</label>
                  <input
                    :id="`amount-${row.id}`"
                    v-model.number="row.edit.amount"
                    type="number"
                    min="0"
                    step="any"
                  />
                </p>
                <p>
                  <label :for="`unit-${row.id}`">劑量單位</label>
                  <select :id="`unit-${row.id}`" v-model="row.edit.unit">
                    <option value="">未標示</option>
                    <option v-for="unit in unitOptions" :key="unit" :value="unit">
                      {{ unit }}
                    </option>
                  </select>
                </p>
                <p>
                  <label :for="`elemental-${row.id}`"
                    >標示載明的元素量（選填，與每份含量使用相同單位）</label
                  >
                  <input
                    :id="`elemental-${row.id}`"
                    v-model.number="row.edit.elemental"
                    type="number"
                    min="0"
                    step="any"
                  />
                </p>
                <button type="button" @click="flow.saveRow(product, row, ingredients)">儲存</button>
                <button type="button" @click="flow.cancelRow(product, row)">取消</button>
              </template>
              <template v-else>
                <span
                  >{{ nameFor(row.value.choice) }}：{{ row.value.amount ?? '未標示' }}
                  {{ row.value.unit }}</span
                >
                <button type="button" :disabled="row.locked" @click="flow.editRow(row)">
                  編輯
                </button>
                <label
                  ><input
                    type="checkbox"
                    :checked="row.locked"
                    @change="
                      flow.setLocked(row, ($event.target as HTMLInputElement).checked, ingredients)
                    "
                  />鎖定變更</label
                >
                <button
                  type="button"
                  :disabled="row.locked"
                  @click="product.rows = product.rows.filter((item) => item.id !== row.id)"
                >
                  移除
                </button>
              </template>
              <p v-if="row.error" role="alert">{{ row.error }}</p>
            </li>
          </ul>
          <button type="button" @click="flow.addRow(product)">＋新增營養素</button>
          <h3>使用者實際服用方式</h3>
          <p v-if="product.draft.label_suggested_intake">
            標示建議：{{ product.draft.label_suggested_intake.raw_text }}（請確認實際服用方式）
          </p>
          <p>
            <label :for="`frequency-${product.id}`">服用頻率</label>
            <select :id="`frequency-${product.id}`" v-model="product.frequency" required>
              <option value="" disabled>請選擇</option>
              <option value="daily">每天</option>
              <option value="alternate_days">每兩天</option>
              <option value="weekly_n_times">每週指定天數</option>
              <option value="cyclic_on_off">週期性服用／停用</option>
              <option value="as_needed">需要時服用（無法量化每日量）</option>
            </select>
          </p>
          <p v-if="product.frequency === 'weekly_n_times'">
            <label :for="`weekly-${product.id}`">每週服用幾天</label>
            <input
              :id="`weekly-${product.id}`"
              v-model.number="product.weekly"
              type="number"
              min="1"
              max="7"
              step="any"
              required
            />
          </p>
          <template v-if="product.frequency === 'cyclic_on_off'">
            <p>
              <label :for="`on-${product.id}`">連續服用天數</label
              ><input
                :id="`on-${product.id}`"
                v-model.number="product.onDays"
                type="number"
                min="0"
                step="any"
                required
              />
            </p>
            <p>
              <label :for="`off-${product.id}`">停止服用天數</label
              ><input
                :id="`off-${product.id}`"
                v-model.number="product.offDays"
                type="number"
                min="0"
                step="any"
                required
              />
            </p>
          </template>
          <p>
            <label :for="`times-${product.id}`">服用當日每日次數</label>
            <select :id="`times-${product.id}`" v-model.number="product.times" required>
              <option value="" disabled>請選擇</option>
              <option v-for="times in [1, 2, 3]" :key="times" :value="times">{{ times }} 次</option>
              <option
                v-if="product.times && ![1, 2, 3].includes(Number(product.times))"
                :value="product.times"
              >
                {{ product.times }} 次（依標示）
              </option>
            </select>
          </p>
          <p>
            <label :for="`intake-${product.id}`"
              >每次服用量 {{ product.doseUnit ? `（${doseLabels[product.doseUnit]}）` : '' }}</label
            >
            <input
              :id="`intake-${product.id}`"
              v-model.number="product.amount"
              type="number"
              min="0"
              step="any"
              :list="`doses-${product.id}`"
              required
            />
            <datalist :id="`doses-${product.id}`">
              <option
                v-for="amount in product.doseUnit ? doseAmounts[product.doseUnit] : []"
                :key="amount"
                :value="amount"
              />
            </datalist>
          </p>
        </section>
        <p v-if="flow.products.length && !canSubmit && !busy">
          有未確認項目，請鎖定所有成分、填寫大於 0 的每份量與實際服用方式。
        </p>
        <button type="submit" :disabled="!canSubmit">保存已核對的保健食品</button>
      </fieldset>
    </form>
    <p v-if="allSaved" role="status">已保存 {{ flow.products.length }} 罐，尚未送出評估。</p>
    <button type="button" disabled>產生報告（尚未開放）</button>
    <p v-if="busy" role="status">{{ stage }}</p>
  </main>
</template>
