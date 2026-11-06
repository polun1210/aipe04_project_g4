<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getCatalog, type Ingredient } from '../api/catalog'
import type { Report, ReportNutrient } from '../api/reports'
import { taipeiDateTime } from '../api/reports'
import { unitLabel } from '../api/supplements'
const props = defineProps<{ report: Report }>()
// 完整編號是 UUID，太長；畫面與 PDF 只顯示前 8 碼，方便口頭或紙本對照（完整編號仍在網址與資料裡）
const REPORT_ID_LENGTH = 8
function shortReportId(id: string) {
  return id.replace(/-/g, '').slice(0, REPORT_ID_LENGTH).toUpperCase()
}
// 範圍外成分清單預設收合；列印／另存 PDF 前強制展開，列印後還原
const outOfScopeDetails = ref<HTMLDetailsElement | null>(null)
const nutrientDetails = ref<HTMLDetailsElement[]>([])
let nutrientDetailsOpenedForPrint: HTMLDetailsElement[] = []
let openedBeforePrint = false
function expandForPrint() {
  const el = outOfScopeDetails.value
  openedBeforePrint = !!el && !el.open
  if (el) el.open = true
  nutrientDetailsOpenedForPrint = nutrientDetails.value.filter((detail) => !detail.open)
  nutrientDetailsOpenedForPrint.forEach((detail) => {
    detail.open = true
  })
}
function restoreAfterPrint() {
  if (outOfScopeDetails.value && openedBeforePrint) outOfScopeDetails.value.open = false
  openedBeforePrint = false
  nutrientDetailsOpenedForPrint.forEach((detail) => {
    detail.open = false
  })
  nutrientDetailsOpenedForPrint = []
}
onMounted(() => {
  window.addEventListener('beforeprint', expandForPrint)
  window.addEventListener('afterprint', restoreAfterPrint)
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeprint', expandForPrint)
  window.removeEventListener('afterprint', restoreAfterPrint)
})
const ingredients = ref<Ingredient[]>([])
const nutrientNames = computed(
  () =>
    new Map([
      ...ingredients.value.map((item) => [item.code, item.display_name_zh] as const),
      ...props.report.nutrients.map((item) => [item.nutrient_code, item.display_name_zh] as const),
    ]),
)
watch(
  () =>
    props.report.disclosures.drug_source_not_counted.some((code) => !nutrientNames.value.has(code)),
  async (missingNames) => {
    if (!missingNames) return
    try {
      ingredients.value = (await getCatalog()).ingredients
    } catch {
      // 目錄暫時無法取得時保留原代碼，仍顯示完整揭露。
    }
  },
  { immediate: true },
)
const advice: Record<string, string> = {
  separate_timing: '錯開服用',
  inform_provider: '告知醫師或藥師',
  consult_before_combining: '併用前先與醫師或藥師討論',
}
const citations = computed(() =>
  Array.from(
    new Map(
      props.report.interactions.flatMap((item) =>
        item.triggers.flatMap((trigger) =>
          trigger.citations.map((citation) => [citation.citation_id, citation] as const),
        ),
      ),
    ).values(),
  ),
)
function ulText(nutrient: ReportNutrient) {
  const ul = nutrient.ul
  if (!ul) return '未訂定可比較的上限，不進行數值比對。'
  const percent = new Intl.NumberFormat('zh-TW', { maximumFractionDigits: 1 }).format(
    ul.ratio * 100,
  )
  const templates: Record<string, string> = {
    exceeded_supplement_only: '已超過補充劑來源上限攝取量',
    percent_supplement_only: `已達補充劑來源上限的 ${percent}%`,
    exceeded_total_intake: '補充劑來源已超過總攝取上限（未含飲食）',
    percent_total_intake: `補充劑已達總攝取上限的 ${percent}%（未含飲食）`,
  }
  return templates[ul.phrasing] ?? '請依上限數據與醫師或藥師討論。'
}
// 每項營養素獨立縮放，保留右側空間，讓建議量與 UL 刻度都落在圖內。
const nutrientCharts = computed(() =>
  props.report.nutrients.map((nutrient) => {
    const peak = nutrient.peak_intake_from_supplements
    const recommended = nutrient.recommended_total_intake.value
    const ul = nutrient.ul?.ul_value
    const maximum = Math.max(peak, recommended, ul ?? 0, 1) * 1.15
    const percent = (value: number) => `${(value / maximum) * 100}%`
    return {
      nutrient,
      greenWidth: percent(ul === undefined ? peak : Math.min(peak, ul)),
      redWidth: percent(ul === undefined ? 0 : Math.max(peak - ul, 0)),
      recommendedPosition: percent(recommended),
      ulPosition: ul === undefined ? undefined : percent(ul),
      stackedLabels: ul !== undefined && Math.abs(recommended - ul) / maximum < 0.38,
    }
  }),
)
function ulScopeLabel(nutrient: ReportNutrient) {
  return nutrient.ul?.scope === 'supplement_only' ? '僅補充劑' : '含飲食'
}
const footnotes = computed(() => props.report.footnotes ?? [])
function withPeriod(text: string) {
  return text.endsWith('。') ? text : `${text}。`
}
function sourceUrl(url: string | null) {
  return url && /^https?:\/\//i.test(url) ? url : undefined
}
</script>

<template>
  <article class="report-content">
    <h1>我的營養補充評估報告</h1>
    <p>
      報告編號：{{ shortReportId(report.report_id) }}｜產生時間：{{
        taipeiDateTime(report.generated_at)
      }}（台灣時間）
    </p>
    <p>{{ report.summary }}</p>
    <section aria-labelledby="report-profile">
      <h2 id="report-profile">
        <span class="section-index" aria-hidden="true">01</span>使用者基本資料
      </h2>
      <p>
        年齡：{{ report.profile.age }}；性別：{{
          report.profile.sex === 'male'
            ? '男'
            : report.profile.sex === 'female'
              ? '女'
              : report.profile.sex
        }}
      </p>
      <p>
        已提供的疾病：{{
          report.profile.known_conditions.map((item) => item.display_name_zh).join('、') ||
          '未勾選本系統涵蓋的慢性病'
        }}
      </p>
      <p>
        用藥：{{
          report.profile.drugs.map((item) => item.raw_name).join('、') || '你沒有提供用藥資料'
        }}
      </p>
      <p>保健食品：{{ report.products.map((item) => item.display_name).join('、') }}</p>
    </section>
    <section aria-labelledby="report-nutrients">
      <h2 id="report-nutrients">
        <span class="section-index" aria-hidden="true">02</span>營養素攝取量與上限比對
      </h2>
      <details>
        <summary>單位說明</summary>
        <ul>
          <li>毫克（mg）、微克（ug）與公克（g）是重量單位；大卡（kcal）是熱量單位。</li>
          <li>國際單位（IU）用於表示生物活性。</li>
          <li>α-TE 是 α-生育醇當量，用於表示維生素 E 的活性；毫克 α-TE 是其單位。</li>
          <li>NE 是菸鹼素當量；毫克 NE 是菸鹼素的當量單位。</li>
          <li>「其他單位」表示後端以 other 標示的單位；未認識的單位代碼會保留原文。</li>
        </ul>
      </details>
      <p>僅計算補充劑攝取量；建議量包含飲食，因此無法據此判定不足。</p>
      <div v-if="report.nutrients.length" class="nutrient-chart-legend">
        <span><i class="nutrient-legend-green" aria-hidden="true"></i>補充劑單日峰值</span>
        <span><i class="nutrient-legend-red" aria-hidden="true"></i>超過上限部分</span>
        <span
          ><i class="nutrient-legend-recommended" aria-hidden="true"></i
          >建議總攝取量（含飲食）</span
        >
        <span><i class="nutrient-legend-ul" aria-hidden="true"></i>上限 UL</span>
      </div>
      <details v-if="report.nutrients.length" class="nutrient-chart-help">
        <summary>圖表說明</summary>
        <p class="nutrient-chart-note">
          灰色背景不代表需要補足的缺口，綠色不代表足夠或安全。
          各營養素獨立縮放，長條長度不可跨營養素比較。建議量與上限可能涵蓋不同來源，請依刻度標示閱讀。
        </p>
      </details>
      <p v-if="!report.nutrients.length">本份報告沒有列出相關營養素。</p>
      <section
        v-for="{ nutrient, ...chart } in nutrientCharts"
        :key="nutrient.nutrient_code"
        class="nutrient-chart-card"
      >
        <div class="nutrient-chart-heading">
          <h3>
            {{ nutrient.display_name_zh }}{{ nutrient.basis === 'estimated' ? '（推估）' : '' }}
          </h3>
          <span
            >補充劑單日峰值 {{ nutrient.peak_intake_from_supplements }}
            {{ unitLabel(nutrient.unit) }}</span
          >
        </div>
        <p
          v-if="nutrient.average_intake_from_supplements !== nutrient.peak_intake_from_supplements"
          class="nutrient-chart-note"
        >
          平均每日 {{ nutrient.average_intake_from_supplements }}
          {{ unitLabel(nutrient.unit) }}；本圖以上述單日峰值比對上限。
        </p>
        <div class="nutrient-chart">
          <div
            class="nutrient-chart-labels"
            :class="{ 'has-ul': nutrient.ul, 'stacked-labels': chart.stackedLabels }"
          >
            <span
              class="nutrient-chart-label nutrient-label-recommended"
              :style="{ '--position': chart.recommendedPosition }"
            >
              建議量 {{ nutrient.recommended_total_intake.value }} {{ unitLabel(nutrient.unit) }}
              <small>含飲食</small>
            </span>
            <span
              v-if="nutrient.ul"
              class="nutrient-chart-label nutrient-label-ul"
              :style="{ '--position': chart.ulPosition }"
            >
              上限 {{ nutrient.ul.ul_value }} {{ unitLabel(nutrient.unit) }}
              <small>{{ ulScopeLabel(nutrient) }}</small>
            </span>
          </div>
          <div class="nutrient-chart-visual" aria-hidden="true">
            <div class="nutrient-chart-track">
              <span class="nutrient-chart-green" :style="{ width: chart.greenWidth }"></span>
              <span class="nutrient-chart-red" :style="{ width: chart.redWidth }"></span>
              <span
                class="nutrient-chart-marker nutrient-chart-recommended"
                :style="{ left: chart.recommendedPosition }"
              ></span>
              <span
                v-if="nutrient.ul"
                class="nutrient-chart-marker nutrient-chart-ul"
                :style="{ left: chart.ulPosition }"
              ></span>
            </div>
          </div>
        </div>
        <p :class="{ 'nutrient-ul-alert': nutrient.ul?.exceeded }">{{ ulText(nutrient) }}</p>
        <details ref="nutrientDetails" class="nutrient-chart-details">
          <summary>查看詳細資料</summary>
          <p>
            平均每日補充劑攝取量：{{ nutrient.average_intake_from_supplements }}
            {{ unitLabel(nutrient.unit) }}
          </p>
          <p>
            建議總攝取量（含飲食，{{
              nutrient.recommended_total_intake.reference_type.toUpperCase()
            }}）：{{ nutrient.recommended_total_intake.value }} {{ unitLabel(nutrient.unit) }}
          </p>
          <p v-if="nutrient.ul">上限適用來源：{{ ulScopeLabel(nutrient) }}。</p>
          <p v-if="nutrient.narration">{{ nutrient.narration }}</p>
        </details>
        <p v-if="nutrient.intake_from_drugs !== null">
          另列藥品來源：{{ nutrient.intake_from_drugs }}
          {{ unitLabel(nutrient.unit) }}，不納入上述補充劑上限比例。
        </p>
      </section>
    </section>
    <section aria-labelledby="report-interactions">
      <h2 id="report-interactions">
        <span class="section-index" aria-hidden="true">03</span>交互作用
      </h2>
      <p v-if="!report.interactions.length">本份報告未列出交互作用；這不代表已排除所有風險。</p>
      <section
        v-for="interaction in report.interactions"
        :key="interaction.ingredient_code"
        :class="{ 'interaction-review': interaction.requires_professional_review }"
      >
        <h3>{{ interaction.display_name_zh }}</h3>
        <p v-if="interaction.narration">
          {{ interaction.narration
          }}<sup
            v-for="number in interaction.footnote_numbers ?? []"
            :key="number"
            class="footnote-ref"
            >[{{ number }}]</sup
          >
        </p>
        <p v-if="interaction.requires_professional_review">請與醫師或藥師討論。</p>
        <ul>
          <li v-for="trigger in interaction.triggers" :key="trigger.rule_id">
            {{ trigger.condition_display_name_zh }}：{{ withPeriod(trigger.reason_zh) }}
          </li>
        </ul>
      </section>
    </section>
    <section aria-labelledby="report-advice">
      <h2 id="report-advice"><span class="section-index" aria-hidden="true">04</span>改善建議</h2>
      <p v-if="!report.interactions.length">本份報告未提供特定交互作用建議。</p>
      <ul>
        <template v-for="interaction in report.interactions" :key="interaction.ingredient_code">
          <li v-for="trigger in interaction.triggers" :key="trigger.rule_id">
            {{ interaction.display_name_zh }}／{{ trigger.condition_display_name_zh }}：
            {{ advice[trigger.advice_code] ?? trigger.advice_code }}
            <span v-if="trigger.separation_hours !== null"
              >（間隔 {{ trigger.separation_hours }} 小時）</span
            >
          </li>
        </template>
      </ul>
    </section>
    <section v-if="footnotes.length" aria-labelledby="report-footnotes" class="report-footnotes">
      <h2 id="report-footnotes">參考資料</h2>
      <ol>
        <li v-for="note in footnotes" :key="note.number" :value="note.number">
          <span
            >[{{ note.number }}] {{ note.source_name }} — {{ note.title }}（{{
              note.section
            }}）</span
          >
          <a
            v-if="sourceUrl(note.url)"
            :href="sourceUrl(note.url)"
            target="_blank"
            rel="noopener noreferrer"
            >查看來源</a
          >
          <details>
            <summary>原文節錄</summary>
            <p>{{ note.excerpt }}</p>
          </details>
        </li>
      </ol>
    </section>
    <section aria-labelledby="report-disclosures">
      <h2 id="report-disclosures">
        <span class="section-index" aria-hidden="true">05</span>評估範圍與資料來源
      </h2>
      <p>
        涵蓋 {{ report.disclosures.covered_known_conditions.length }} 種慢性病、{{
          report.disclosures.covered_drug_classes.length
        }}
        類用藥與
        {{ report.disclosures.covered_nutrients.length }} 項成分，未涵蓋所有疾病、用藥與成分。
      </p>
      <p v-if="report.disclosures.drugs_none">你沒有提供用藥資料。</p>
      <p v-if="report.disclosures.known_conditions_none">
        你未勾選本系統涵蓋的慢性病，不代表沒有疾病。
      </p>
      <p v-if="report.disclosures.healthy_population_caveat">
        DRIs 為健康族群參考值，慢性病個別需要請與醫師或藥師討論。
      </p>
      <p v-if="report.disclosures.peak_same_day_assumption">非每日服用產品的峰值採同日服用假設。</p>
      <p v-if="report.disclosures.drug_source_not_counted.length">
        下列營養素的藥品來源未納入補充劑上限比例：{{
          report.disclosures.drug_source_not_counted
            .map((code) => nutrientNames.get(code) ?? code)
            .join('、')
        }}。
      </p>
      <details
        v-if="report.disclosures.out_of_scope_ingredients.length"
        ref="outOfScopeDetails"
        class="out-of-scope-details"
      >
        <summary>
          不在評估範圍的成分（共 {{ report.disclosures.out_of_scope_ingredients.length }} 項）
        </summary>
        <ul class="out-of-scope-list">
          <li v-for="(name, index) in report.disclosures.out_of_scope_ingredients" :key="index">
            {{ name }}
          </li>
        </ul>
      </details>
      <p v-if="report.disclosures.unresolved_ingredients.length" class="disclosure-unassessed">
        無法確認的成分：{{ report.disclosures.unresolved_ingredients.join('、') }}，請諮詢藥師。
      </p>
      <p v-if="report.disclosures.out_of_scope_drugs.length">
        不在評估範圍的藥品：{{ report.disclosures.out_of_scope_drugs.join('、') }}
      </p>
      <p v-if="report.disclosures.unresolved_drugs.length" class="disclosure-unassessed">
        無法確認的藥品：{{
          report.disclosures.unresolved_drugs.join('、')
        }}，無法判斷是否有交互作用，請諮詢藥師。
      </p>
      <details>
        <summary>查看出處</summary>
        <p v-if="!citations.length">本次評估沒有觸發任何規則，因此沒有可列的出處。</p>
        <section v-for="citation in citations" :key="citation.citation_id">
          <h3>{{ citation.source }} — {{ citation.section }}</h3>
          <p>{{ citation.quote }}</p>
          <p>
            適用族群：{{ citation.population }}；版本：{{
              citation.source_version ?? '未提供'
            }}；查閱日期：{{ citation.retrieved_at }}
          </p>
          <a
            v-if="sourceUrl(citation.url)"
            :href="sourceUrl(citation.url)"
            target="_blank"
            rel="noopener noreferrer"
            >查看來源 {{ citation.citation_id }}</a
          >
        </section>
      </details>
    </section>
  </article>
</template>

<style scoped>
.nutrient-chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  margin: 20px 0 12px;
  font-size: 0.875rem;
}
.nutrient-chart-legend > span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.nutrient-chart-legend i {
  display: inline-block;
  width: 18px;
  height: 14px;
}
.nutrient-legend-green,
.nutrient-chart-green {
  background: #d4e887;
}
.nutrient-legend-red,
.nutrient-chart-red {
  background: #c95045;
}
.nutrient-legend-recommended {
  border-left: 2px dashed #142332;
}
.nutrient-legend-ul {
  border-left: 3px solid #142332;
}
.nutrient-chart-note {
  color: #536370;
  font-size: 0.875rem;
  line-height: 1.7;
}
.nutrient-chart-card {
  break-inside: avoid;
}
.nutrient-chart {
  margin: 16px 0 20px;
}
.nutrient-chart-heading {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px 16px;
}
.nutrient-chart-heading h3 {
  margin: 0;
}
.nutrient-chart-heading > span {
  font-size: 0.95rem;
}
.nutrient-chart-labels {
  position: relative;
  height: 50px;
}
.nutrient-chart-labels.stacked-labels {
  height: 96px;
}
.nutrient-chart-label {
  position: absolute;
  left: clamp(90px, var(--position), calc(100% - 90px));
  transform: translateX(-50%);
  width: 180px;
  text-align: center;
  font-size: 0.8125rem;
  line-height: 1.5;
}
.nutrient-chart-label small {
  display: block;
  color: #536370;
  font-size: inherit;
}
.nutrient-label-recommended {
  top: 0;
}
.nutrient-label-ul {
  top: 0;
  font-weight: 600;
}
.stacked-labels .nutrient-label-ul {
  top: 46px;
}
.nutrient-label-recommended::before {
  content: '';
  display: inline-block;
  height: 12px;
  border-left: 2px dashed #142332;
  margin-right: 6px;
}
.nutrient-label-ul::before {
  content: '';
  display: inline-block;
  height: 12px;
  border-left: 3px solid #142332;
  margin-right: 6px;
}
.nutrient-chart-track {
  position: relative;
  display: flex;
  height: 24px;
  background: #e8eced;
  border-radius: 4px;
}
.nutrient-chart-green,
.nutrient-chart-red {
  display: block;
  height: 100%;
  flex-shrink: 0;
}
.nutrient-chart-marker {
  position: absolute;
  top: -7px;
  bottom: -7px;
  width: 0;
}
.nutrient-chart-recommended {
  border-left: 2px dashed #142332;
  z-index: 1;
}
.nutrient-chart-ul {
  border-left: 3px solid #142332;
}
.nutrient-ul-alert {
  color: #943e24;
  font-weight: 600;
}
@media (max-width: 600px) {
  .nutrient-chart-labels.has-ul {
    height: 96px;
  }
  .has-ul .nutrient-label-ul {
    top: 46px;
  }
}
@media print {
  .nutrient-chart,
  .nutrient-chart-legend {
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
}
</style>
