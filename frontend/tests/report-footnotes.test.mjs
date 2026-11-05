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
  .replace(/import \{ unitLabel[^\n]*\n/, 'const unitLabel = (u) => u\n')
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

const nutrient = (code, ul, extra = {}) => ({
  nutrient_code: code,
  display_name_zh: `營養${code}`,
  peak_intake_from_supplements: 10,
  average_intake_from_supplements: 7,
  intake_from_drugs: null,
  unit: 'mg',
  basis: 'measured',
  recommended_total_intake: { reference_type: 'rda', value: 99 },
  ul,
  narration: null,
  ...extra,
})
const ul = (ratio, exceeded) => ({
  ul_value: 100,
  ratio,
  exceeded,
  scope: 'supplement_only',
  phrasing: exceeded ? 'exceeded_supplement_only' : 'percent_supplement_only',
})
// 取出某個營養素的區塊 HTML
const block = (html, code) => html.split('<section').find((s) => s.includes(`營養${code}`)) ?? ''

test('超過上限：紅色橫條與「超過上限」標籤，標籤顯示實際百分比', async () => {
  const html = block(
    await render(report({ nutrients: [nutrient('A', ul(1.49, true))] })),
    'A',
  )
  assert.match(html, /nutrient-bar--exceeded/)
  assert.doesNotMatch(html, /nutrient-bar--within/)
  assert.match(html, /149% 超過上限/)
  assert.match(html, /nutrient-bar-ul/)
})

test('未超過上限：藍色橫條，長度為比例除以 150%', async () => {
  const html = block(await render(report({ nutrients: [nutrient('B', ul(0.75, false))] })), 'B')
  assert.match(html, /nutrient-bar--within/)
  assert.doesNotMatch(html, /nutrient-bar--exceeded/)
  assert.match(html, /width:\s*50%/)
  assert.match(html, /75%/)
  assert.doesNotMatch(html, /75% 超過上限/)
})

test('剛好 100% 且後端標為超過時視為超過上限', async () => {
  const html = block(await render(report({ nutrients: [nutrient('C', ul(1, true))] })), 'C')
  assert.match(html, /nutrient-bar--exceeded/)
  assert.match(html, /100% 超過上限/)
})

test('超過滿格（150%）時橫條畫滿，標籤仍顯示實際百分比', async () => {
  const html = block(await render(report({ nutrients: [nutrient('D', ul(2.2, true))] })), 'D')
  assert.match(html, /width:\s*100%/)
  assert.match(html, /220% 超過上限/)
})

test('沒有上限：不畫橫條，只列文字', async () => {
  const html = block(await render(report({ nutrients: [nutrient('E', null)] })), 'E')
  assert.doesNotMatch(html, /nutrient-bar/)
  assert.match(html, /未訂定可比較的上限/)
})

test('平均、建議總攝取量與藥品來源收進營養素可展開區塊，且不在橫條上', async () => {
  const html = block(
    await render(
      report({ nutrients: [nutrient('F', ul(0.5, false), { intake_from_drugs: 3 })] }),
    ),
    'F',
  )
  const m = html.match(/<details[^>]*class="nutrient-details"[^>]*>([\s\S]*?)<\/details>/)
  assert.ok(m, '應有 nutrient-details')
  assert.doesNotMatch(m[0], / open/)
  assert.match(m[1], /平均每日：7 /)
  assert.match(m[1], /建議總攝取量（含飲食，RDA）：99 /)
  assert.match(m[1], /另列藥品來源：3 /)
  assert.doesNotMatch(html.replace(m[0], ''), /建議總攝取量/)
})
