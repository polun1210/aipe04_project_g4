// Run with: npm run test:medicine-flow
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
  URLSearchParams,
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
      const bindings = id.endsWith('MedicineUploadView.vue')
        ? 'startRecognition, startNextBatch, goToReview, selectedImages, receivedDraft, errorMessages'
        : id.endsWith('MedicineReviewView.vue')
          ? 'setAllLocked, bulkMessage, searchDrug, selectDrug, clearLookup, lookups, saveMedicine, cancelEditing'
          : 'submit, ingredients, error, canSubmit'
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
const { useMedicineFlowStore } = await source('../src/stores/medicineFlow.ts')
const { useSupplementFlowStore } = await source('../src/stores/supplementFlow.ts')
const uploadModule = await source('../src/views/MedicineUploadView.vue')
const reviewModule = await source('../src/views/SupplementReviewView.vue')
const medicineReviewModule = await source('../src/views/MedicineReviewView.vue')
const fixture = JSON.parse(
  await readFile(new URL('../../docs/schemas/examples/04_drug_draft.json', import.meta.url)),
)
let medicine, supplement, calls
const file = () => new File(['image'], 'package.png', { type: 'image/png' })
function addBatch(id) {
  medicine.addDrugBatch([file(), file()], { ...structuredClone(fixture), draft_id: id })
}
function confirm() {
  for (const row of medicine.medicines) medicine.setLocked(row, true)
}
function readyReview() {
  supplement.products.push({
    id: 'supplement-draft',
    draft: { source_images: [] },
    files: [],
    name: 'Test',
    servingSize: 1,
    doseUnit: 'tablet',
    frequency: 'daily',
    times: 1,
    amount: 1,
    rows: [
      {
        rowId: null,
        locked: true,
        editing: false,
        value: { choice: 'calcium', amount: 100, unit: 'mg', form: '', elemental: null },
      },
    ],
    savedPayload: null,
    savedProductId: null,
  })
  const review = reviewModule.setup()
  review.ingredients.value = [
    { code: 'calcium', category: 'target_nutrient', accepted_units: ['mg'] },
  ]
  assert.equal(review.canSubmit.value, true)
  return review
}
beforeEach(() => {
  pinia.setActivePinia(pinia.createPinia())
  medicine = useMedicineFlowStore()
  supplement = useSupplementFlowStore()
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
      path === '/api/products' ? { product_id: 'product-1' } : { case_id: 'case-1' },
    )
  }
})

test('batches A and B append, preserving edits, lock state, manual rows and sources', () => {
  addBatch('A')
  const row = medicine.medicines[0]
  medicine.startEditing(row)
  row.draftName = 'Corrected medicine'
  medicine.saveMedicine(row)
  medicine.setLocked(row, true)
  medicine.addMedicine()
  const manual = medicine.medicines.at(-1)
  manual.draftName = 'Manual medicine in progress'
  const count = medicine.medicines.length
  addBatch('B')
  addBatch('B')
  assert.equal(medicine.drugBatches.length, 2)
  assert.equal(medicine.medicines.length, count + fixture.rows.length)
  assert.equal(row.name, 'Corrected medicine')
  assert.equal(row.isLocked, true)
  assert.equal(manual.draftName, 'Manual medicine in progress')
  assert.equal(manual.isEditing, true)
  assert.equal(medicine.findSourceFile('A', 'img-01').name, 'package.png')
})

test('recognition failure retains previous batches and selected images for retry', async () => {
  addBatch('A')
  const upload = uploadModule.setup()
  upload.selectedImages.value = [1, 2].map((id) => ({ id, file: file(), isLoaded: true }))
  request = async () => {
    throw new Error('recognition failed')
  }
  await upload.startRecognition()
  assert.equal(medicine.drugBatches.length, 1)
  assert.equal(upload.selectedImages.value.length, 2)
  assert.equal(upload.receivedDraft.value, null)
  request = async () => Response.json({ ...fixture, draft_id: 'B' })
  await upload.startRecognition()
  await upload.startRecognition() // Successful batch is frozen, so no duplicate recognition.
  assert.equal(medicine.drugBatches.length, 2)
  upload.startNextBatch()
  assert.equal(upload.selectedImages.value.length, 0)
  assert.equal(medicine.drugBatches.length, 2)
})

test('successful A+B assessment and confirmed report navigation reset medicines; C starts clean', async () => {
  addBatch('A')
  addBatch('B')
  confirm()
  const review = readyReview()
  const push = router.push.bind(router)
  router.push = async (path) => {
    assert.equal(medicine.drugBatches.length, 2) // Still present until navigation completes.
    await push(path)
  }
  await review.submit()
  assert.equal(review.error.value, '')
  assert.equal(medicine.drugBatches.length, 0)
  assert.equal(medicine.medicines.length, 0)
  assert.equal(medicine.confirmedDrugs.length, 0)
  assert.equal(medicine.allConfirmed, false)
  assert.equal(supplement.products.length, 0) // Existing supplement completion behavior.
  const sent = JSON.parse(calls.find((call) => call.path === '/api/assessments').body)
  assert.deepEqual([...new Set(sent.drugs.selected.map((drug) => drug.draft_id))], ['A', 'B'])
  addBatch('C')
  assert.deepEqual(
    Array.from(medicine.drugBatches, (batch) => batch.draft.draft_id),
    ['C'],
  )
  assert.ok(medicine.medicines.every((row) => row.draftId === 'C'))
})

test('assessment failure retains medicines and reuses saved product when retrying', async () => {
  addBatch('A')
  confirm()
  const review = readyReview()
  const success = request
  request = async (path, options) => {
    if (path === '/api/assessments') throw new Error('assessment failed')
    return success(path, options)
  }
  await review.submit()
  assert.equal(medicine.drugBatches.length, 1)
  assert.equal(supplement.products.length, 1)
  assert.equal(supplement.products[0].savedProductId, 'product-1')
  request = success
  await review.submit()
  assert.equal(calls.filter((call) => call.path === '/api/products').length, 1)
  assert.equal(medicine.medicines.length, 0)
})

for (const mode of ['throw', 'abort', 'redirect', 'wrong-case']) {
  test(`navigation ${mode} retains both stores and retries without duplicate product/assessment`, async () => {
    addBatch('A')
    confirm()
    const review = readyReview()
    const success = router.push.bind(router)
    router.push = async () => {
      if (mode === 'throw') throw new Error('navigation failed')
      if (mode === 'abort') {
        router.currentRoute.value = { name: 'report', params: { caseId: 'case-1' } }
        return abortedNavigation()
      }
      router.currentRoute.value = {
        name: mode === 'redirect' ? 'home' : 'report',
        params: { caseId: 'other' },
      }
    }
    await review.submit()
    assert.equal(medicine.drugBatches.length, 1)
    assert.equal(supplement.caseId, 'case-1')
    assert.equal(supplement.products.length, 1)
    router.push = success
    await review.submit()
    assert.equal(calls.filter((call) => call.path === '/api/products').length, 1)
    assert.equal(calls.filter((call) => call.path === '/api/assessments').length, 1)
    assert.equal(medicine.drugBatches.length, 0)
  })
}
async function abortedNavigation() {
  const testRouter = vueRouter.createRouter({
    history: vueRouter.createMemoryHistory(),
    routes: [
      { path: '/', component: {} },
      { path: '/blocked', component: {} },
    ],
  })
  await testRouter.push('/')
  testRouter.beforeEach(() => false)
  return testRouter.push('/blocked')
}

test('leaving an unfinished flow keeps medicine data; medicine reset never clears supplements', () => {
  addBatch('A')
  confirm()
  const review = readyReview()
  reviewModule.setup() // Re-entering does not clear either store.
  assert.equal(medicine.drugBatches.length, 1)
  assert.equal(supplement.products.length, 1)
  medicine.resetFlow()
  assert.equal(supplement.products.length, 1)
  assert.equal(review.canSubmit.value, true) // Supplement-only flow still works.
})

test('supplement-only submission still completes without medicine data', async () => {
  const review = readyReview()
  await review.submit()
  assert.equal(review.error.value, '')
  const sent = JSON.parse(calls.find((call) => call.path === '/api/assessments').body)
  assert.deepEqual(sent.drugs, { selected: [], none_selected: true })
  assert.equal(supplement.products.length, 0)
})

test('invalid recognition response preserves the current round and retry images', async () => {
  addBatch('A')
  const upload = uploadModule.setup()
  upload.selectedImages.value = [{ id: 1, file: file(), isLoaded: true }]
  request = async () => Response.json({ draft_id: 'invalid' })
  await upload.startRecognition()
  assert.equal(medicine.drugBatches.length, 1)
  assert.equal(upload.selectedImages.value.length, 1)
  assert.equal(upload.receivedDraft.value, null)
  assert.equal(upload.errorMessages.value.length, 1)
})

test('bulk controls lock eligible rows across batches and skip blank/editing rows without submitting', () => {
  addBatch('A')
  addBatch('B')
  const original = JSON.stringify(medicine.drugBatches.map((batch) => batch.draft))
  const editing = medicine.medicines[0]
  medicine.startEditing(editing)
  editing.draftName = 'unsaved change'
  medicine.medicines[1].name = '  '
  medicine.addMedicine()
  const review = medicineReviewModule.setup()
  review.setAllLocked(true)
  assert.match(review.bulkMessage.value, /3 筆無法鎖定/)
  assert.equal(editing.name, fixture.rows[0].raw_name)
  assert.equal(editing.draftName, 'unsaved change')
  assert.equal(editing.isEditing, true)
  assert.equal(medicine.allConfirmed, false)
  assert.equal(medicine.confirmedDrugs.length, 0)
  assert.ok(medicine.medicines.slice(2, -1).every((row) => row.isLocked))
  review.setAllLocked(false)
  assert.ok(medicine.medicines.every((row) => !row.isLocked))
  assert.equal(JSON.stringify(medicine.drugBatches.map((batch) => batch.draft)), original)
  assert.equal(calls.length, 0)
})

test('bulk lock confirms valid manual rows and unlock revokes submission readiness', () => {
  medicine.addMedicine()
  const row = medicine.medicines[0]
  row.draftName = '阿斯匹靈'
  medicine.saveMedicine(row)
  medicine.setAllLocked(true)
  assert.equal(medicine.allConfirmed, true)
  assert.equal(medicine.confirmedDrugs[0].name, '阿斯匹靈')
  medicine.startEditing(row)
  assert.equal(row.isEditing, false)
  medicine.setAllLocked(false)
  assert.equal(medicine.allConfirmed, false)
  assert.equal(medicine.confirmedDrugs.length, 0)
  assert.equal(calls.length, 0)
})

const lookupResponse = {
  mapped: {
    raw_name: '立普妥',
    scope_status: 'in_scope',
    active_ingredient_code: 'atorvastatin',
    drug_class_codes: [],
  },
  candidates: [
    {
      active_ingredient_code: 'atorvastatin',
      display_name_zh: '阿托伐他汀',
      english_name: 'Atorvastatin',
      matched_name: '立普妥',
      drug_class_codes: [],
    },
  ],
}

test('lookup uses API candidates; selection preserves OCR and source; assessment payload contains name only', async () => {
  addBatch('A')
  const row = medicine.medicines[0]
  const original = JSON.stringify(medicine.drugBatches[0].draft)
  medicine.startEditing(row)
  row.draftName = '立普妥'
  request = async (path) => {
    calls.push({ path })
    return Response.json(lookupResponse)
  }
  const review = medicineReviewModule.setup()
  await review.searchDrug(row)
  assert.equal(calls[0].path, `/api/drugs/lookup?${new URLSearchParams({ name: '立普妥' })}`)
  review.selectDrug(row, { target: { value: 'atorvastatin' } })
  assert.equal(row.draftName, '阿托伐他汀')
  assert.equal(row.name, fixture.rows[0].raw_name)
  assert.equal(row.isLocked, false)
  review.saveMedicine(row)
  medicine.setAllLocked(true)
  const confirmed = medicine.confirmedDrugs[0]
  assert.equal(confirmed.name, '阿托伐他汀')
  assert.equal(confirmed.draft_id, 'A')
  assert.equal(confirmed.row_id, fixture.rows[0].row_id)
  assert.equal('scope_status' in confirmed, false)
  assert.equal('active_ingredient_code' in confirmed, false)
  assert.equal(JSON.stringify(medicine.drugBatches[0].draft), original)
  assert.ok(calls.every((call) => call.path.startsWith('/api/drugs/lookup?')))
})

test('lookup ignores superseded responses and input changes; cancellation does not save', async () => {
  medicine.addMedicine()
  const row = medicine.medicines[0]
  const review = medicineReviewModule.setup()
  const pending = []
  request = () => new Promise((resolve) => pending.push(resolve))
  row.draftName = 'old'
  const oldSearch = review.searchDrug(row)
  row.draftName = 'new'
  review.clearLookup(row)
  const newSearch = review.searchDrug(row)
  pending[1](Response.json({ mapped: { scope_status: 'unresolved' }, candidates: [] }))
  await newSearch
  pending[0](Response.json(lookupResponse))
  await oldSearch
  assert.equal(review.lookups.value[row.id].result.candidates.length, 0)
  assert.equal(row.draftName, 'new')
  const lateSearch = review.searchDrug(row)
  review.cancelEditing(row)
  pending[2](Response.json(lookupResponse))
  await lateSearch
  assert.equal(medicine.medicines.length, 0)
  assert.equal(review.lookups.value[row.id], undefined)
})

test('lookup failures keep manual input and permit retry; empty names never query', async () => {
  medicine.addMedicine()
  const row = medicine.medicines[0]
  const review = medicineReviewModule.setup()
  await review.searchDrug(row)
  assert.equal(calls.length, 0)
  row.draftName = '未知藥名'
  request = async () => {
    throw new Error('offline')
  }
  await review.searchDrug(row)
  assert.ok(review.lookups.value[row.id].error)
  assert.equal(row.draftName, '未知藥名')
  request = async () => Response.json({ mapped: { scope_status: 'unresolved' }, candidates: [] })
  await review.searchDrug(row)
  assert.equal(review.lookups.value[row.id].error, '')
  assert.equal(review.lookups.value[row.id].result.mapped.scope_status, 'unresolved')
  review.saveMedicine(row)
  assert.equal(row.name, '未知藥名')
})
