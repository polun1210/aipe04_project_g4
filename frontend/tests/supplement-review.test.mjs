// Run with: npm run test:supplement-review
// Execute the actual stores and SFC setup scripts; browser rendering is tested manually.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { beforeEach, test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { compileTemplate, parse } from '@vue/compiler-sfc'
import { renderToString } from 'vue/server-renderer'
import * as vue from 'vue'
import * as pinia from 'pinia'
import * as vueRouter from 'vue-router'

let router
let request
const context = vm.createContext({
  File,
  FormData,
  Headers,
  URL,
  crypto,
  structuredClone,
  console,
  fetch: (...args) => request(...args),
})
const modules = new Map()
async function load(id) {
  if (modules.has(id)) return modules.get(id)
  let module
  if (!id.startsWith('file:')) {
    const exports =
      id === 'vue'
        ? { ...vue, inject: (_key, fallback) => fallback, onMounted() {}, onUnmounted() {} }
        : id === 'pinia'
          ? pinia
          : { ...vueRouter, useRouter: () => router, onBeforeRouteLeave() {} }
    module = new vm.SyntheticModule(
      Object.keys(exports),
      function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
      },
      { context },
    )
  } else {
    let source = await readFile(new URL(id), 'utf8')
    if (id.endsWith('.vue')) {
      source = parse(source).descriptor.scriptSetup.content
      const ast = ts.createSourceFile(id, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
      const imports = ast.statements.filter(ts.isImportDeclaration)
      const body = ast.statements.filter((statement) => !ts.isImportDeclaration(statement))
      const bindings = `submit, ingredients, error, canSubmit, busy, catalogBusy,
         flow, medicine, previews, selectedImageId, confirmedCount, reviewRows, outOfScopeRows,
         isTestExtraction, loadCatalog, doseLabels, doseAmounts, unitOptions, chooseNutrient,
         nameFor, isReviewFrequency, stage, productLockedCount, doseOptions`
      source = `${imports.map((s) => s.getText(ast)).join('\n')}
        export function setup() {
          ${body.map((s) => s.getText(ast)).join('\n')}
          return { ${bindings} }
        }`
    }
    const code = ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
    }).outputText
    module = new vm.SourceTextModule(code, { context, identifier: id })
  }
  modules.set(id, module)
  await module.link((specifier, parent) =>
    load(
      specifier.startsWith('.') ? new URL(`${specifier}.ts`, parent.identifier).href : specifier,
    ),
  )
  return module
}
async function source(path) {
  const module = await load(new URL(path, import.meta.url).href)
  if (module.status !== 'evaluated') await module.evaluate()
  return module.namespace
}
const { useSupplementFlowStore, productReady, submissionFor, isReviewFrequency } = await source(
  '../src/stores/supplementFlow.ts',
)
const { useMedicineFlowStore } = await source('../src/stores/medicineFlow.ts')
const reviewModule = await source('../src/views/SupplementReviewView.vue')
const reviewSource = await readFile(
  new URL('../src/views/SupplementReviewView.vue', import.meta.url),
  'utf8',
)
const compiled = compileTemplate({
  source: parse(reviewSource).descriptor.template.content,
  id: 'review-test',
  compilerOptions: { expressionPlugins: ['typescript'] },
})
assert.deepEqual(compiled.errors, [])
const templateCode = ts.transpileModule(compiled.code, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText
const templateModule = new vm.SourceTextModule(templateCode, { context })
await templateModule.link((specifier) => load(specifier))
await templateModule.evaluate()
async function renderReview(review) {
  const app = vue.createSSRApp({ setup: () => review, render: templateModule.namespace.render })
  app.component('RouterLink', {
    setup:
      (_, { slots }) =>
      () =>
        vue.h('a', slots.default?.()),
  })
  app.component('ReviewImageGallery', { render: () => vue.h('div') })
  return renderToString(app)
}
const ingredients = [{ code: 'calcium', category: 'target_nutrient', accepted_units: ['mg'] }]
let flow, calls
function addProduct(id, extraRows = []) {
  flow.addBatch([], {
    product_id: id,
    product_name: `產品 ${id}`,
    source_images: [],
    serving_info: { serving_size: 2, dose_unit: 'tablet' },
    label_suggested_intake: {
      raw_text: '每日 2 次，每次 1 錠',
      times_per_day: 2,
      amount_per_time: 1,
    },
    nutrients: [
      {
        row_id: 'row-1',
        raw_name: '鈣',
        standard_code: 'calcium',
        scope_status: 'in_scope',
        source_image_id: null,
        per_serving: 100,
        unit: 'mg',
        nutrient_form_code: null,
        stated_elemental_amount: null,
      },
      ...extraRows,
    ],
    extraction_meta: { ocr_version: 'stub-t01' },
  })
  const product = flow.products.at(-1)
  product.frequency = 'daily'
  return product
}
function setupReview() {
  const review = reviewModule.setup()
  review.ingredients.value = ingredients
  return review
}
const totalReviewRows = (review) => flow.products.flatMap(review.reviewRows)
const totalLockedCount = (review) => totalReviewRows(review).filter((row) => row.locked).length
const json = (value) => JSON.parse(JSON.stringify(value))
const withoutLockState = () =>
  json(flow.products).map((product) => ({
    ...product,
    rows: product.rows.map(({ locked: _locked, error: _error, ...row }) => row),
  }))
beforeEach(() => {
  pinia.setActivePinia(pinia.createPinia())
  flow = useSupplementFlowStore()
  calls = []
  router = {
    currentRoute: vue.ref({ name: 'supplement-review', params: {} }),
    async push(path) {
      this.currentRoute.value = { name: 'report', params: { caseId: path.split('/').at(-1) } }
    },
  }
  request = async (path, options) => {
    calls.push({ path, body: options?.body })
    return Response.json(
      path === '/api/products' ? { product_id: `saved-${calls.length}` } : { case_id: 'case-1' },
    )
  }
})

test('single dose uses a select and keeps an extracted value outside the common options', async () => {
  const product = addProduct('A')
  product.draft.label_suggested_intake.amount_per_time = 7
  product.amount = 7
  const review = setupReview()
  const html = await renderReview(review)
  assert.match(html, /<select[^>]*id="intake-A"[^>]*>/)
  assert.match(html, /<option value="7">7 錠<\/option>/)
  assert.doesNotMatch(html, /<datalist/)
  product.amount = 2
  assert.ok(review.doseOptions(product).includes(7))
  assert.equal(submissionFor(product).user_intake.amount_per_time, 2)
})

test('product bulk actions affect only the selected product and render independent controls', async () => {
  const a = addProduct('A')
  const b = addProduct('B')
  a.rows.push({ ...json(a.rows[0]), id: 'second' })
  const review = setupReview()
  const before = withoutLockState()
  flow.lockAllRows(ingredients, a)
  assert.ok(a.rows.every((row) => row.locked))
  assert.ok(b.rows.every((row) => !row.locked))
  assert.equal(review.productLockedCount(a), 2)
  assert.equal(review.productLockedCount(b), 0)
  const html = await renderReview(review)
  const panels = html.split('class="product-panel"').slice(1)
  assert.match(panels[0], /disabled[^>]*>\s*一鍵鎖定/)
  assert.doesNotMatch(panels[1], /disabled[^>]*>\s*一鍵鎖定/)
  assert.doesNotMatch(panels[0], /disabled[^>]*>\s*全部解除鎖定/)
  assert.match(panels[1], /disabled[^>]*>\s*全部解除鎖定/)
  flow.lockAllRows(ingredients, b)
  a.rows[0].value.amount = -1
  flow.unlockAllRows(a)
  assert.ok(a.rows.every((row) => !row.locked))
  assert.ok(b.rows.every((row) => row.locked))
  a.rows[0].value.amount = 100
  assert.deepEqual(withoutLockState(), before)
  assert.equal(calls.length, 0)
})

test('bulk lock covers all batches, skips editing and invalid rows, and changes no input data', () => {
  const a = addProduct('A')
  const b = addProduct('B')
  flow.addRow(a)
  a.rows[1].edit.choice = 'calcium'
  a.rows[1].edit.amount = 300 // Unsaved edits must remain intact.
  b.rows.push({ ...json(b.rows[0]), id: 'invalid', value: { ...b.rows[0].value, amount: -1 } })
  const review = setupReview()
  const before = withoutLockState()
  flow.lockAllRows(ingredients)
  assert.equal(totalReviewRows(review).length, 4)
  assert.equal(totalLockedCount(review), 2)
  assert.equal(a.rows[1].locked, false)
  assert.equal(a.rows[1].editing, true)
  assert.equal(b.rows[1].locked, false)
  assert.ok(b.rows[1].error)
  assert.deepEqual(withoutLockState(), before)
  assert.equal(calls.length, 0) // Locking does not submit or call any API.
  assert.equal(review.canSubmit.value, false)
  flow.lockAllRows(ingredients)
  assert.equal(totalLockedCount(review), 2) // Safe to repeat.
})

test('bulk unlock clears every flag including invalid rows without altering input data', () => {
  const a = addProduct('A')
  addProduct('B')
  flow.lockAllRows(ingredients)
  a.rows[0].value.amount = -1 // Simulate validation changing after locking.
  const before = withoutLockState()
  flow.unlockAllRows()
  assert.ok(flow.products.every((product) => product.rows.every((row) => !row.locked)))
  assert.deepEqual(withoutLockState(), before)
  flow.editRow(a.rows[0])
  assert.equal(a.rows[0].editing, true)
  assert.equal(calls.length, 0)
})

test('individual checkbox locking still uses validation and can be mixed with bulk locking', () => {
  const a = addProduct('A')
  const b = addProduct('B')
  flow.setLocked(a.rows[0], true, ingredients)
  assert.equal(a.rows[0].locked, true)
  assert.equal(b.rows[0].locked, false)
  flow.lockAllRows(ingredients)
  flow.setLocked(a.rows[0], false, ingredients)
  assert.equal(a.rows[0].locked, false)
  assert.equal(b.rows[0].locked, true)
  b.rows[0].locked = false
  b.rows[0].value.unit = 'g'
  flow.setLocked(b.rows[0], true, ingredients)
  assert.equal(b.rows[0].locked, false)
})

test('missing catalog and invalid nutrient values cannot be bulk locked', () => {
  const a = addProduct('A')
  flow.lockAllRows([])
  assert.equal(a.rows[0].locked, false)
  for (const value of [
    { choice: '' },
    { amount: null },
    { amount: -1 },
    { unit: 'other' },
    { elemental: -1 },
  ]) {
    a.rows[0].value = {
      choice: 'calcium',
      amount: 100,
      unit: 'mg',
      form: '',
      elemental: null,
      ...value,
    }
    flow.lockAllRows(ingredients)
    assert.equal(a.rows[0].locked, false)
  }
})

test('newly added products keep earlier edits and locks and participate in the next bulk action', () => {
  const a = addProduct('A')
  flow.editRow(a.rows[0])
  a.rows[0].edit.amount = 250
  flow.saveRow(a, a.rows[0], ingredients)
  flow.lockAllRows(ingredients)
  const b = addProduct('B')
  const review = setupReview()
  assert.equal(totalLockedCount(review), 1)
  assert.equal(a.rows[0].value.amount, 250)
  assert.equal(b.rows[0].locked, false)
  flow.lockAllRows(ingredients)
  assert.equal(totalLockedCount(review), 2)
  assert.equal(a.rows[0].value.amount, 250)
})

for (const frequency of ['daily', 'alternate_days', 'weekly_n_times', 'cyclic_on_off']) {
  test(`${frequency} still validates and serializes daily count and single dose unchanged`, () => {
    const a = addProduct('A')
    a.frequency = frequency
    a.weekly = 3
    a.onDays = 5
    a.offDays = 2
    flow.lockAllRows(ingredients)
    assert.equal(isReviewFrequency(frequency), true)
    assert.equal(productReady(a, ingredients), true)
    const intake = submissionFor(a).user_intake
    assert.equal(intake.frequency_type, frequency)
    assert.equal(intake.times_per_day, 2)
    assert.equal(intake.amount_per_time, 1)
    assert.equal(intake.days_per_week, frequency === 'weekly_n_times' ? 3 : null)
    assert.equal(intake.cycle_on_days, frequency === 'cyclic_on_off' ? 5 : null)
    assert.equal(intake.cycle_off_days, frequency === 'cyclic_on_off' ? 2 : null)
  })
}

test('bulk lock does not bypass product, schedule or medicine validation', () => {
  const a = addProduct('A')
  flow.lockAllRows(ingredients)
  const review = setupReview()
  for (const [key, value] of [
    ['name', ''],
    ['servingSize', 0],
    ['times', 0],
    ['amount', 0],
    ['frequency', ''],
  ]) {
    const original = a[key]
    a[key] = value
    assert.equal(review.canSubmit.value, false)
    a[key] = original
  }
  a.frequency = 'weekly_n_times'
  for (const weekly of [null, 0, 8]) {
    a.weekly = weekly
    assert.equal(review.canSubmit.value, false)
  }
  a.frequency = 'cyclic_on_off'
  a.onDays = 5
  a.offDays = 0
  assert.equal(review.canSubmit.value, false)
  a.frequency = 'daily'
  assert.equal(review.canSubmit.value, true)
  useMedicineFlowStore().addMedicine()
  assert.equal(review.canSubmit.value, false)
})

test('legacy as_needed stays unchanged and cannot submit until explicitly replaced', async () => {
  const a = addProduct('A')
  a.frequency = 'as_needed'
  flow.lockAllRows(ingredients)
  const review = setupReview()
  assert.equal(a.frequency, 'as_needed')
  assert.equal(review.canSubmit.value, false)
  assert.throws(() => submissionFor(a), /請重新選擇有效的服用頻率/)
  await review.submit()
  assert.equal(calls.length, 0)
  assert.equal(a.frequency, 'as_needed')
  assert.equal(a.times, 2)
  assert.equal(a.amount, 1)
  a.frequency = 'daily' // Explicit user choice.
  await review.submit()
  assert.equal(review.error.value, '')
  const saved = JSON.parse(calls.find((call) => call.path === '/api/products').body)
  assert.equal(saved.user_intake.frequency_type, 'daily')
  assert.equal(saved.user_intake.times_per_day, 2)
  assert.equal(saved.user_intake.amount_per_time, 1)
})

test('bulk-locked multi-product assessment resets supplement store only after report navigation', async () => {
  addProduct('A')
  addProduct('B')
  const review = setupReview()
  flow.lockAllRows(ingredients)
  assert.equal(totalLockedCount(review), 2)
  assert.equal(review.canSubmit.value, true)
  router.push = async () => {
    assert.equal(flow.products.length, 2)
    router.currentRoute.value = { name: 'report', params: { caseId: 'case-1' } }
  }
  await review.submit()
  assert.equal(review.error.value, '')
  assert.equal(calls.filter((call) => call.path === '/api/products').length, 2)
  const assessment = JSON.parse(calls.find((call) => call.path === '/api/assessments').body)
  assert.equal(assessment.product_ids.length, 2)
  assert.equal(flow.products.length, 0)
  assert.equal(flow.caseId, null)
  assert.equal(flow.assessmentPayload, null)
  assert.equal(totalLockedCount(review), 0)
  const c = addProduct('C')
  assert.equal(flow.products.length, 1)
  assert.equal(c.rows[0].locked, false)
})

for (const failure of ['assessment', 'navigation']) {
  test(`${failure} failure preserves locked rows and supports retry`, async () => {
    const a = addProduct('A')
    flow.lockAllRows(ingredients)
    const review = setupReview()
    const successRequest = request
    const successPush = router.push.bind(router)
    if (failure === 'assessment') {
      request = async (path, options) => {
        if (path === '/api/assessments') throw new Error('assessment failed')
        return successRequest(path, options)
      }
    } else
      router.push = async () => {
        throw new Error('navigation failed')
      }
    await review.submit()
    assert.equal(flow.products.length, 1)
    assert.equal(a.rows[0].locked, true)
    request = successRequest
    router.push = successPush
    await review.submit()
    assert.equal(review.error.value, '')
    assert.equal(calls.filter((call) => call.path === '/api/products').length, 1)
    assert.equal(calls.filter((call) => call.path === '/api/assessments').length, 1)
    assert.equal(flow.products.length, 0)
  })
}

test('empty round bulk actions are harmless', () => {
  const review = setupReview()
  flow.lockAllRows(ingredients)
  flow.unlockAllRows()
  assert.equal(totalReviewRows(review).length, 0)
  assert.equal(review.canSubmit.value, false)
  assert.equal(calls.length, 0)
})

function scopeRow(id, scope = 'out_of_scope') {
  return {
    row_id: id,
    raw_name: `成分 ${id}`,
    standard_code: null,
    scope_status: scope,
    source_image_id: 'img-01',
    per_serving: null,
    unit: null,
    nutrient_form_code: null,
    stated_elemental_amount: null,
    requires_user_input: true,
  }
}

test('mixed scopes render separate sections with name-only collapsed out-of-scope rows', async () => {
  const a = addProduct('A', [scopeRow('outside'), scopeRow('unknown', 'unresolved')])
  const review = setupReview()
  assert.equal(review.reviewRows(a).length, 2)
  assert.equal(review.outOfScopeRows(a).length, 1)
  assert.equal(totalReviewRows(review).length, 2)
  flow.lockAllRows(ingredients)
  assert.equal(totalLockedCount(review), 2)
  assert.equal(review.confirmedCount(a), 2)
  assert.equal(a.rows[1].locked, false)
  assert.equal(a.rows[2].locked, true) // Unresolved still requires confirmation.
  const html = await renderReview(review)
  const [outside] = html.match(/<details\b[\s\S]*?<\/details>/g) ?? []
  assert.ok(outside)
  assert.match(outside, /目前不在評估範圍（1 項）/)
  assert.match(outside, /<li>成分 outside<\/li>/)
  assert.doesNotMatch(outside, /<(?:input|select|button)\b|辨識原文|每份含量/)
  assert.doesNotMatch(outside.split('>')[0], /\bopen\b/)
  const confirmation = html.slice(
    html.indexOf('id="needs-confirmation-A"'),
    html.indexOf('<details'),
  )
  assert.match(confirmation, /需要你確認/)
  assert.match(confirmation, /成分 unknown/)
  assert.doesNotMatch(confirmation, /成分 outside/)
  assert.match(html, /max="2"/)
})

test('out-of-scope rows stay unchanged, unlocked and serialized through submit and retries', async () => {
  const a = addProduct('A', [scopeRow('outside')])
  const b = addProduct('B', [scopeRow('outside-B')])
  const beforeDrafts = json(flow.products.map((product) => product.draft))
  const outsideBefore = json(a.rows[1])
  const review = setupReview()
  flow.lockAllRows(ingredients)
  flow.setLocked(a.rows[1], true, ingredients)
  assert.deepEqual(json(a.rows[1]), outsideBefore)
  assert.equal(totalReviewRows(review).length, 2)
  assert.equal(productReady(a, ingredients), true)
  assert.equal(productReady(b, ingredients), true)
  assert.equal(review.canSubmit.value, true)
  assert.equal(submissionFor(a).nutrients.length, 2)
  assert.deepEqual(json(submissionFor(a).nutrients[1]), {
    row_id: 'outside',
    standard_code: null,
    scope_status: 'out_of_scope',
    nutrient_form_code: null,
    per_serving: null,
    unit: null,
    stated_elemental_amount: null,
  })
  flow.unlockAllRows()
  assert.equal(review.canSubmit.value, false)
  flow.lockAllRows(ingredients)
  router.push = async () => {
    throw new Error('navigation failed')
  }
  await review.submit()
  assert.equal(review.error.value, '無法完成操作，請確認網路與後端服務後再試。')
  assert.deepEqual(json(flow.products.map((product) => product.draft)), beforeDrafts)
  assert.deepEqual(json(a.rows[1]), outsideBefore)
  router.push = async () => {
    router.currentRoute.value = { name: 'report', params: { caseId: 'case-1' } }
  }
  await review.submit()
  assert.equal(review.error.value, '')
  assert.equal(calls.filter((call) => call.path === '/api/products').length, 2)
  assert.ok(
    calls
      .filter((call) => call.path === '/api/products')
      .every((call) =>
        JSON.parse(call.body).nutrients.some((row) => row.scope_status === 'out_of_scope'),
      ),
  )
  assert.equal(flow.products.length, 0)
})

test('out-of-scope-only products can submit with no nutrient locks', async () => {
  const a = addProduct('A', [scopeRow('outside')])
  a.rows.shift()
  a.draft.nutrients.shift()
  const before = json(a.draft)
  const review = setupReview()
  flow.lockAllRows(ingredients)
  assert.equal(totalReviewRows(review).length, 0)
  assert.equal(totalLockedCount(review), 0)
  assert.equal(a.rows[0].locked, false)
  assert.equal(productReady(a, ingredients), true)
  assert.equal(review.canSubmit.value, true)
  const html = await renderReview(review)
  assert.doesNotMatch(html, /<progress|一鍵鎖定|type="checkbox"/)
  assert.match(html, /目前沒有需要確認的成分/)
  await review.submit()
  assert.equal(review.error.value, '')
  assert.equal(JSON.parse(calls[0].body).nutrients[0].scope_status, 'out_of_scope')
  assert.deepEqual(json(a.draft), before)
})

test('unresolved and in-scope rows must still be saved, valid and locked', () => {
  const a = addProduct('A', [scopeRow('outside'), scopeRow('unknown', 'unresolved')])
  flow.setLocked(a.rows[0], true, ingredients)
  const review = setupReview()
  assert.equal(review.canSubmit.value, false)
  flow.setLocked(a.rows[2], true, ingredients)
  assert.equal(review.canSubmit.value, true)
  flow.unlockAllRows()
  flow.editRow(a.rows[0])
  a.rows[0].edit.amount = -1
  flow.saveRow(a, a.rows[0], ingredients)
  flow.lockAllRows(ingredients)
  assert.equal(review.canSubmit.value, false)
  assert.equal(a.rows[0].editing, true)
  assert.equal(a.rows[1].locked, false)
  assert.equal(a.rows[2].locked, true)
})

test('saving an unresolved row as out-of-scope moves it without deleting the original draft', () => {
  const a = addProduct('A', [scopeRow('unknown', 'unresolved')])
  const original = json(a.draft)
  const review = setupReview()
  flow.editRow(a.rows[1])
  a.rows[1].edit.choice = 'out_of_scope'
  assert.equal(review.reviewRows(a).length, 2) // Do not hide an unsaved edit.
  flow.saveRow(a, a.rows[1], ingredients)
  assert.equal(review.reviewRows(a).length, 1)
  assert.equal(review.outOfScopeRows(a).length, 1)
  assert.equal(a.rows[1].locked, false)
  assert.equal(a.rows[1].rawName, '成分 unknown')
  assert.deepEqual(json(a.draft), original)
  flow.lockAllRows(ingredients)
  assert.equal(review.canSubmit.value, true)
  assert.equal(submissionFor(a).nutrients[1].scope_status, 'out_of_scope')
})
