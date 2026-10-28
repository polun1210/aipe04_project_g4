// Run with: npm run test:supplement-review
// Execute the actual stores and SFC setup scripts; browser rendering is tested manually.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { beforeEach, test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'
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
        ? { ...vue, onMounted() {}, onUnmounted() {} }
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
      const bindings =
        'submit, ingredients, error, canSubmit, nutrientRows, lockedCount, busy, catalogBusy'
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
const ingredients = [{ code: 'calcium', category: 'target_nutrient', accepted_units: ['mg'] }]
let flow, calls
function addProduct(id) {
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
  assert.equal(review.nutrientRows.value.length, 4)
  assert.equal(review.lockedCount.value, 2)
  assert.equal(a.rows[1].locked, false)
  assert.equal(a.rows[1].editing, true)
  assert.equal(b.rows[1].locked, false)
  assert.ok(b.rows[1].error)
  assert.deepEqual(withoutLockState(), before)
  assert.equal(calls.length, 0) // Locking does not submit or call any API.
  assert.equal(review.canSubmit.value, false)
  flow.lockAllRows(ingredients)
  assert.equal(review.lockedCount.value, 2) // Safe to repeat.
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
  assert.equal(review.lockedCount.value, 1)
  assert.equal(a.rows[0].value.amount, 250)
  assert.equal(b.rows[0].locked, false)
  flow.lockAllRows(ingredients)
  assert.equal(review.lockedCount.value, 2)
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
  assert.equal(review.lockedCount.value, 2)
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
  assert.equal(review.lockedCount.value, 0)
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
  assert.equal(review.nutrientRows.value.length, 0)
  assert.equal(review.canSubmit.value, false)
  assert.equal(calls.length, 0)
})
