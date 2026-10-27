// Run with: npm run test:supplement-upload
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
let created, revoked, cleanups
const context = vm.createContext({
  File,
  FormData,
  Headers,
  URL: {
    createObjectURL(file) {
      const url = URL.createObjectURL(file)
      created.push(url)
      return url
    },
    revokeObjectURL(url) {
      revoked.push(url)
      URL.revokeObjectURL(url)
    },
  },
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
        ? {
            ...vue,
            onMounted() {},
            onUnmounted(callback) {
              cleanups.push(callback)
            },
          }
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
        'category, productName, categoryError, nameError, showRequiredErrors, images, error, busy, received, canUpload, recognize, nextBatch, selectFiles, remove, previewFailed'
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
const { useSupplementFlowStore, productReady, submissionFor } = await source(
  '../src/stores/supplementFlow.ts',
)
const uploadModule = await source('../src/views/SupplementUploadView.vue')
const fixture = JSON.parse(
  await readFile(new URL('../../docs/schemas/examples/04_supplement_draft.json', import.meta.url)),
)
let flow, upload, calls
const file = (name = 'label.png') => new File(['image'], name, { type: 'image/png' })
function select(name = 'label.png', kind = 'nutrition') {
  const input = { files: [file(name)], value: 'selected' }
  upload.selectFiles({ target: input }, kind)
  assert.equal(input.value, '')
}
function readyImages() {
  select()
  upload.images.value[0].loaded = true // Same state change as the template's @load handler.
}
function validFields() {
  upload.category.value = '  鈣  '
  upload.productName.value = '  我的鈣片  '
}
beforeEach(() => {
  pinia.setActivePinia(pinia.createPinia())
  flow = useSupplementFlowStore()
  calls = []
  created = []
  revoked = []
  cleanups = []
  router = { push: async () => undefined }
  request = async (path, options) => {
    calls.push({ path, body: options.body })
    return Response.json({
      ...fixture,
      product_id: `product-${calls.length}`,
      source_images: [{ image_id: 'img-01', quality_status: 'accepted' }],
      nutrients: fixture.nutrients.filter((row) => row.source_image_id === 'img-01'),
    })
  }
  upload = uploadModule.setup()
})

for (const [description, category, name, missingCategory, missingName] of [
  ['category missing', '', '鈣片', true, false],
  ['category whitespace only', ' \t\u3000 ', '鈣片', true, false],
  ['name missing', '鈣', '', false, true],
  ['name whitespace only', '鈣', ' \t\u3000 ', false, true],
  ['both missing', '', '', true, true],
]) {
  test(`${description}: Chinese validation errors and no API call`, async () => {
    readyImages()
    upload.category.value = category
    upload.productName.value = name
    const image = upload.images.value[0]
    await upload.recognize()
    assert.equal(calls.length, 0)
    assert.equal(flow.products.length, 0)
    assert.equal(upload.showRequiredErrors.value, true)
    assert.equal(Boolean(upload.categoryError.value), missingCategory)
    assert.equal(Boolean(upload.nameError.value), missingName)
    if (missingCategory) assert.match(upload.categoryError.value, /請選擇或輸入保健食品種類/)
    if (missingName) assert.match(upload.nameError.value, /請填寫保健食品名稱/)
    assert.equal(upload.images.value[0], image)
    assert.equal(upload.images.value[0].loaded, true)
    assert.equal(upload.received.value, false)
  })
}

test('correcting missing fields clears errors and permits recognition with the existing API contract', async () => {
  readyImages()
  await upload.recognize()
  assert.equal(calls.length, 0)
  validFields()
  assert.equal(upload.categoryError.value, '')
  assert.equal(upload.nameError.value, '')
  await upload.recognize()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].path, '/api/supplement-drafts')
  assert.deepEqual([...calls[0].body.keys()], ['nutrition_images', 'category'])
  assert.equal(calls[0].body.get('category'), '鈣')
  assert.equal(flow.products[0].name, '我的鈣片')
  assert.equal(flow.products[0].draft.product_name, fixture.product_name) // Preserve OCR original.
  assert.equal(upload.received.value, true)
  await upload.recognize()
  assert.equal(calls.length, 1) // Successful batch is frozen.
})

test('API failure preserves fields and previews and can be retried', async () => {
  readyImages()
  validFields()
  const success = request
  request = async () => {
    throw new Error('API unavailable')
  }
  await upload.recognize()
  assert.ok(upload.error.value)
  assert.equal(upload.category.value, '  鈣  ')
  assert.equal(upload.productName.value, '  我的鈣片  ')
  assert.equal(upload.images.value.length, 1)
  assert.equal(upload.images.value[0].loaded, true)
  assert.equal(revoked.length, 0)
  assert.equal(upload.busy.value, false)
  assert.equal(upload.received.value, false)
  request = success
  await upload.recognize()
  assert.equal(flow.products.length, 1)
  assert.equal(flow.products[0].name, '我的鈣片')
})

test('second batch requires its own fields and preserves previous product and manual corrections', async () => {
  readyImages()
  validFields()
  await upload.recognize()
  const first = flow.products[0]
  first.name = '人工校對後的名稱'
  first.rows[0].value.amount = 321
  upload.nextBatch()
  assert.equal(upload.category.value, '')
  assert.equal(upload.productName.value, '')
  assert.equal(upload.showRequiredErrors.value, false)
  assert.equal(upload.images.value.length, 0)
  assert.equal(revoked.length, 1)
  readyImages()
  await upload.recognize()
  assert.equal(calls.length, 1)
  upload.category.value = '魚油'
  upload.productName.value = '第二罐魚油'
  await upload.recognize()
  assert.equal(flow.products.length, 2)
  assert.equal(first.name, '人工校對後的名稱')
  assert.equal(first.rows[0].value.amount, 321)
  assert.equal(flow.products[1].name, '第二罐魚油')
})

test('previews still load, remove and fail independently from field validation', async () => {
  select()
  validFields()
  assert.equal(upload.canUpload.value, false)
  await upload.recognize()
  assert.equal(calls.length, 0)
  assert.ok(upload.images.value[0].url.startsWith('blob:'))
  upload.images.value[0].loaded = true
  assert.equal(upload.canUpload.value, true)
  upload.remove(upload.images.value[0].id)
  assert.equal(upload.images.value.length, 0)
  assert.equal(revoked.length, 1)
  select('broken.png')
  upload.previewFailed(upload.images.value[0].id)
  assert.equal(upload.images.value.length, 0)
  assert.match(upload.error.value, /圖片無法讀取/)
  select('remaining.png')
  for (const cleanup of cleanups) cleanup()
  assert.equal(upload.images.value.length, 0)
  assert.equal(revoked.length, 3)
})

test('image grouping and source order are unchanged when sending both image kinds', async () => {
  select('nutrition.png', 'nutrition')
  select('ingredients.png', 'ingredients')
  for (const image of upload.images.value) image.loaded = true
  validFields()
  request = async (path, options) => {
    calls.push({ path, body: options.body })
    return Response.json(fixture)
  }
  await upload.recognize()
  assert.equal(calls[0].body.get('ingredient_images').name, 'ingredients.png')
  assert.equal(calls[0].body.get('nutrition_images').name, 'nutrition.png')
  assert.deepEqual(
    Array.from(flow.products[0].files, (item) => item.name),
    ['ingredients.png', 'nutrition.png'],
  )
})

test('long categories and invalid API responses do not discard current fields or images', async () => {
  readyImages()
  validFields()
  upload.category.value = '鈣'.repeat(31)
  await upload.recognize()
  assert.equal(calls.length, 0)
  assert.match(upload.categoryError.value, /最多 30 字/)
  upload.category.value = '鈣'
  request = async () => Response.json({ product_id: 'invalid' })
  await upload.recognize()
  assert.equal(flow.products.length, 0)
  assert.equal(upload.productName.value, '  我的鈣片  ')
  assert.equal(upload.images.value.length, 1)
  assert.equal(upload.received.value, false)
})

test('review name validation also rejects blank names and submission trims a valid name', async () => {
  readyImages()
  validFields()
  await upload.recognize()
  const product = flow.products[0]
  product.name = ' \t\u3000 '
  assert.equal(productReady(product, []), false)
  product.name = '  使用者確認的名稱  '
  assert.equal(submissionFor(product).product_name, '使用者確認的名稱')
})

test('the optional local name does not change existing callers or overwrite duplicate batch edits', () => {
  flow.addBatch([], fixture)
  assert.equal(flow.products[0].name, fixture.product_name ?? '')
  flow.products[0].name = '已校對'
  flow.addBatch([], fixture, '重複回應')
  assert.equal(flow.products.length, 1)
  assert.equal(flow.products[0].name, '已校對')
})
