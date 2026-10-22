<script setup lang="ts">
import { computed } from 'vue'
import type { Report, ReportNutrient } from '../api/reports'
import { taipeiDateTime } from '../api/reports'
const props = defineProps<{ report: Report }>()
const severity = { priority: '優先處理', attention: '留意', info: '資訊' }
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
    exceeded_supplement_only: '已超過上限攝取量',
    percent_supplement_only: `已達上限攝取量的 ${percent}%`,
    exceeded_total_intake: '補充劑來源已超過上限攝取量',
    percent_total_intake: `補充劑來源已達上限的 ${percent}%（未含飲食）`,
  }
  return templates[ul.phrasing] ?? '請依上限數據與醫師或藥師討論。'
}
function sourceUrl(url: string | null) {
  return url && /^https?:\/\//i.test(url) ? url : undefined
}
</script>

<template>
  <article>
    <h1>我的營養補充評估報告</h1>
    <p role="status">
      目前後端計算與報告仍為示範實作，使用測試帳號與範例內容，並非你的正式健康評估。
    </p>
    <p>產生時間：{{ taipeiDateTime(report.generated_at) }}（台灣時間）</p>
    <p>報告編號：{{ report.report_id }}</p>
    <p>{{ report.summary }}</p>
    <section aria-labelledby="report-profile">
      <h2 id="report-profile">① 使用者基本資料</h2>
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
      <h2 id="report-nutrients">② 營養素攝取量與上限比對</h2>
      <p>補充劑來源與含飲食的建議總攝取量口徑不同，不能直接相減當作缺口。</p>
      <p v-if="!report.nutrients.length">本份報告沒有列出相關營養素。</p>
      <section v-for="nutrient in report.nutrients" :key="nutrient.nutrient_code">
        <h3>
          {{ nutrient.display_name_zh }}{{ nutrient.basis === 'estimated' ? '（推估）' : '' }}
        </h3>
        <p>
          補充劑單日峰值：{{ nutrient.peak_intake_from_supplements }}
          {{ nutrient.unit }}；平均每日：{{ nutrient.average_intake_from_supplements }}
          {{ nutrient.unit }}
        </p>
        <p>
          建議總攝取量（含飲食，{{
            nutrient.recommended_total_intake.reference_type.toUpperCase()
          }}）：{{ nutrient.recommended_total_intake.value }} {{ nutrient.unit }}
        </p>
        <p v-if="nutrient.ul">
          上限：{{ nutrient.ul.ul_value }} {{ nutrient.unit }}。{{ ulText(nutrient) }}
        </p>
        <p v-else>{{ ulText(nutrient) }}</p>
        <p v-if="nutrient.intake_from_drugs !== null">
          另列藥品來源：{{ nutrient.intake_from_drugs }}
          {{ nutrient.unit }}，不納入上述補充劑上限比例。
        </p>
        <p v-if="nutrient.narration">{{ nutrient.narration }}</p>
      </section>
    </section>
    <section aria-labelledby="report-interactions">
      <h2 id="report-interactions">③ 交互作用</h2>
      <p v-if="!report.interactions.length">本份報告未列出交互作用；這不代表已排除所有風險。</p>
      <section v-for="interaction in report.interactions" :key="interaction.ingredient_code">
        <h3>{{ interaction.display_name_zh }}：{{ severity[interaction.severity] }}</h3>
        <p v-if="interaction.narration">{{ interaction.narration }}</p>
        <p v-if="interaction.requires_professional_review">請與醫師或藥師討論。</p>
        <ul>
          <li v-for="trigger in interaction.triggers" :key="trigger.rule_id">
            {{ trigger.condition_display_name_zh }}：{{ trigger.reason_zh }}。
          </li>
        </ul>
      </section>
    </section>
    <section aria-labelledby="report-advice">
      <h2 id="report-advice">④ 改善建議</h2>
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
    <section aria-labelledby="report-disclosures">
      <h2 id="report-disclosures">⑤ 評估範圍與資料來源</h2>
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
      <p v-if="report.disclosures.out_of_scope_ingredients.length">
        不在評估範圍的成分：{{ report.disclosures.out_of_scope_ingredients.join('、') }}
      </p>
      <p v-if="report.disclosures.unresolved_ingredients.length">
        無法確認的成分：{{ report.disclosures.unresolved_ingredients.join('、') }}，請諮詢藥師。
      </p>
      <p v-if="report.disclosures.out_of_scope_drugs.length">
        不在評估範圍的藥品：{{ report.disclosures.out_of_scope_drugs.join('、') }}
      </p>
      <p v-if="report.disclosures.unresolved_drugs.length">
        無法確認的藥品：{{
          report.disclosures.unresolved_drugs.join('、')
        }}，無法判斷是否有交互作用，請諮詢藥師。
      </p>
      <details>
        <summary>查看出處</summary>
        <p v-if="!citations.length">後端未提供出處資料。</p>
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
