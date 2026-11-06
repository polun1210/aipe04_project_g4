// 以 compileScript 內嵌 template 後在 Node 內渲染 ReportContent，驗證腳註顯示。
import assert from 'node:assert/strict'
import { readFile, writeFile, rm } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'

const path = new URL('../src/components/ReportContent.vue', import.meta.url)
const { descriptor } = parse(await readFile(path, 'utf8'))
let code = compileScript(descriptor, { id: 'report-test', inlineTemplate: true }).content
code = ts.transpileModule(code, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText
code = code
  .replace(/import \{ getCatalog[^\n]*\n/, 'const getCatalog = async () => ({ ingredients: [] })\n')
  .replace(/import \{ taipeiDateTime[^\n]*\n/, 'const taipeiDateTime = (v) => v\n')
  .replace(/import \{ unitLabel[^\n]*\n/, 'const unitLabel = (v) => v\n')
  .replace(/import [^\n]*['"]\.\.\/api\/[^\n]*\n/g, '')
const tmp = new URL('./.report-content.tmp.mjs', import.meta.url)
await writeFile(tmp, code)
const { default: ReportContent } = await import(tmp.href)
await rm(tmp)

const trigger = {
  rule_id: 'R-1',
  condition_display_name_zh: '降血脂藥',
  reason_zh: '原因',
  advice_code: 'inform_provider',
  separation_hours: null,
  citations: [],
}
const note = (number, url) => ({
  number,
  chunk_id: `c${number}`,
  source: 'nccih',
  source_name: `來源${number}`,
  title: `標題${number}`,
  section: '章節',
  url,
  excerpt: `節錄${number}`,
})
function report(extra, footnoteNumbers) {
  return {
    report_id: 'r',
    generated_at: 'now',
    summary: 's',
    profile: { age: 40, sex: 'male', known_conditions: [], drugs: [] },
    products: [],
    nutrients: [],
    interactions: [
      {
        ingredient_code: 'x',
        display_name_zh: '紅麴',
        narration: '說明',
        requires_professional_review: false,
        triggers: [trigger],
        ...(footnoteNumbers ? { footnote_numbers: footnoteNumbers } : {}),
      },
    ],
    disclosures: {
      covered_known_conditions: [],
      covered_drug_classes: [],
      covered_nutrients: [],
      drug_source_not_counted: [],
      out_of_scope_ingredients: [],
      unresolved_ingredients: [],
      out_of_scope_drugs: [],
      unresolved_drugs: [],
    },
    ...extra,
  }
}
const render = (r) => renderToString(createSSRApp(ReportContent, { report: r }))

test('營養素長條僅將超過 UL 的部分標紅，建議量不作為紅色門檻', async () => {
  const nutrient = (peak, ul = 2000) => ({
    nutrient_code: 'calcium',
    display_name_zh: '鈣',
    unit: 'mg',
    basis: 'confirmed',
    peak_intake_from_supplements: peak,
    average_intake_from_supplements: peak,
    intake_from_drugs: null,
    recommended_total_intake: { reference_type: 'rda', value: 1000 },
    ul:
      ul === null
        ? null
        : {
            ul_value: ul,
            ratio: peak / ul,
            exceeded: peak >= ul,
            scope: 'total_intake',
            phrasing: peak >= ul ? 'exceeded_total_intake' : 'percent_total_intake',
          },
    narration: null,
  })
  for (const peak of [0, 300, 1300, 2000]) {
    const html = await render(report({ nutrients: [nutrient(peak)] }))
    assert.match(html, /class="nutrient-chart-red" style="width:0%;"/)
    assert.match(html, /nutrient-chart-recommended/)
    assert.match(html, /灰色背景不代表需要補足的缺口/)
  }
  const excess = await render(report({ nutrients: [nutrient(2300)] }))
  const red = Number(excess.match(/class="nutrient-chart-red" style="width:([\d.]+)%;"/)[1])
  const green = Number(excess.match(/class="nutrient-chart-green" style="width:([\d.]+)%;"/)[1])
  assert.ok(Math.abs(red / green - 300 / 2000) < 1e-10)
  assert.match(excess, /class="nutrient-ul-alert"/)
  const noUl = await render(report({ nutrients: [nutrient(2300, null)] }))
  assert.doesNotMatch(noUl, /class="nutrient-chart-marker nutrient-chart-ul"/)
  assert.match(noUl, /未訂定可比較的上限，不進行數值比對/)
  assert.match(noUl, /class="nutrient-chart-red" style="width:0%;"/)
})

test('上限來源文案分開顯示，詳細資料預設收合，移除繪圖用端點數字', async () => {
  const nutrient = {
    nutrient_code: 'magnesium',
    display_name_zh: '鎂',
    unit: 'mg',
    basis: 'confirmed',
    peak_intake_from_supplements: 300,
    average_intake_from_supplements: 150,
    intake_from_drugs: null,
    recommended_total_intake: { reference_type: 'rda', value: 360 },
    ul: {
      ul_value: 350,
      ratio: 300 / 350,
      exceeded: false,
      scope: 'supplement_only',
      phrasing: 'percent_supplement_only',
    },
    narration: '原始補充說明',
  }
  const html = await render(report({ nutrients: [nutrient] }))
  assert.match(html, /已達補充劑來源上限的 85.7%/)
  assert.match(html, /<small>僅補充劑<\/small>/)
  assert.match(html, /stacked-labels/)
  assert.match(html, /平均每日 150 mg；本圖以上述單日峰值比對上限/)
  assert.match(
    html,
    /<details[^>]*class="nutrient-chart-details"[^>]*><summary>查看詳細資料<\/summary>/,
  )
  assert.doesNotMatch(html, /nutrient-chart-details"[^>]* open/)
  assert.match(html, /原始補充說明<\/p><\/details>/)
  assert.doesNotMatch(html, /414 mg|nutrient-chart-axis/)
  const total = await render(
    report({
      nutrients: [
        {
          ...nutrient,
          ul: { ...nutrient.ul, scope: 'total_intake', phrasing: 'percent_total_intake' },
        },
      ],
    }),
  )
  assert.match(total, /補充劑已達總攝取上限的 85.7%（未含飲食）/)
  assert.doesNotMatch(total, /<small>僅補充劑<\/small>/)
})

test('有腳註時顯示上標編號與參考資料清單', async () => {
  const html = await render(
    report({ footnotes: [note(1, 'https://a.example/x'), note(2, 'https://b.example/y')] }, [1, 2]),
  )
  assert.match(html, /footnote-ref[^>]*>\[1\]<\/sup>/)
  assert.match(html, /footnote-ref[^>]*>\[2\]<\/sup>/)
  assert.match(html, /參考資料/)
  assert.match(html, /來源1 — 標題1/)
  assert.match(html, /href="https:\/\/b\.example\/y"/)
  assert.match(html, /<details><summary>原文節錄<\/summary><p>節錄2<\/p>/)
})

test('沒有腳註（空陣列或缺欄位）時不渲染參考資料', async () => {
  for (const r of [report({ footnotes: [] }, []), report({}, undefined)]) {
    const html = await render(r)
    assert.doesNotMatch(html, /參考資料/)
    assert.doesNotMatch(html, /footnote-ref/)
  }
})

test('不安全網址不產生連結但仍顯示該則', async () => {
  const html = await render(report({ footnotes: [note(1, 'javascript:alert(1)')] }, [1]))
  assert.doesNotMatch(html, /javascript:/)
  assert.match(html, /來源1 — 標題1/)
  assert.doesNotMatch(html, /查看來源/)
})

test('原因已以句號結尾時不重複補句號，沒有句號時才補', async () => {
  const withReason = (reason) => {
    const r = report({})
    r.interactions[0].triggers = [{ ...trigger, reason_zh: reason }]
    return r
  }
  const done = await render(withReason('已有句號。'))
  assert.match(done, /降血脂藥：已有句號。</)
  assert.doesNotMatch(done, /。。/)
  assert.match(await render(withReason('沒有句號')), /降血脂藥：沒有句號。</)
})

test('範圍外成分以收合清單呈現並顯示總數，無則不渲染', async () => {
  const names = ['成分甲', '成分乙', '成分丙']
  const html = await render(
    report({
      disclosures: { ...report({}).disclosures, out_of_scope_ingredients: names },
    }),
  )
  assert.match(html, /<details[^>]*class="out-of-scope-details"[^>]*>/)
  assert.doesNotMatch(html, /out-of-scope-details"[^>]* open/)
  assert.match(html, /<summary>\s*不在評估範圍的成分（共 3 項）\s*<\/summary>/)
  assert.equal((html.match(/<li>\s*成分[甲乙丙]\s*<\/li>/g) ?? []).length, 3)
  assert.doesNotMatch(html, /成分甲、成分乙/)
  assert.doesNotMatch(await render(report({})), /不在評估範圍的成分/)
})

test('無法確認的成分維持警示段落、不收合', async () => {
  const html = await render(
    report({
      disclosures: { ...report({}).disclosures, unresolved_ingredients: ['X', 'Y'] },
    }),
  )
  assert.match(html, /disclosure-unassessed[^>]*>\s*無法確認的成分：X、Y，請諮詢藥師。/)
})

test('報告編號只顯示前 8 碼大寫，不顯示完整 UUID', async () => {
  const html = await render(report({ report_id: '892fe767-f933-4388-a7f5-d858add6374c' }))
  assert.match(html, /報告編號：892FE767｜產生時間/)
  assert.doesNotMatch(html, /892fe767-f933/)
})
