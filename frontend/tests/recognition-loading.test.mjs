import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { beforeEach, test } from 'node:test'
import vm from 'node:vm'
import { compileScript, compileStyle, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as pinia from 'pinia'

// Compile and mount the real SFCs, including the shared loading component, without a DOM package.
let request, navigation, guards
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
const pendingModules = new Map()
const exposures = {
  MedicineUploadView:
    'selectedImages, isUploading, canUpload, startRecognition, receivedDraft, errorMessages, goToReview',
  SupplementUploadView:
    'images, busy, canUpload, category, productName, recognize, received, error, review',
}
function load(id) {
  // Vue SFC sibling imports can request the same dependency concurrently.
  // Cache the promise too, so instanceof checks use one ApiError constructor.
  if (!pendingModules.has(id)) pendingModules.set(id, createModule(id))
  return pendingModules.get(id)
}
async function createModule(id) {
  if (modules.has(id)) return modules.get(id)
  let module
  if (!id.startsWith('file:')) {
    const exports =
      id === 'vue'
        ? { ...vue, vModelText: {} } // This renderer sets model refs directly; it does not emulate DOM input events.
        : id === 'pinia'
          ? pinia
          : {
              useRouter: () => ({
                push: async (path) => {
                  navigation.push(path)
                },
              }),
              onBeforeRouteLeave: (guard) => guards.push(guard),
            }
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
      const name = id.split('/').at(-1).replace('.vue', '')
      if (exposures[name]) {
        source = source.replace('</script>', `\ndefineExpose({ ${exposures[name]} })\n</script>`)
      }
      const { descriptor } = parse(source)
      if (descriptor.scriptSetup) {
        source = compileScript(descriptor, {
          id: name,
          inlineTemplate: true,
          templateOptions: { compilerOptions: { hoistStatic: false } },
        }).content
      } else {
        const compiled = compileTemplate({
          source: descriptor.template.content,
          id: name,
          compilerOptions: { hoistStatic: false },
        })
        assert.deepEqual(compiled.errors, [])
        source = `${compiled.code}\nexport default { render }`
      }
    }
    const code = ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
    }).outputText
    module = new vm.SourceTextModule(code, { context, identifier: id })
  }
  modules.set(id, module)
  await module.link((specifier, parent) =>
    load(
      specifier.startsWith('.')
        ? new URL(specifier.endsWith('.vue') ? specifier : `${specifier}.ts`, parent.identifier)
            .href
        : specifier,
    ),
  )
  return module
}
async function source(path) {
  const module = await load(new URL(path, import.meta.url).href)
  if (module.status !== 'evaluated') await module.evaluate()
  return module.namespace
}
const { default: MedicineUpload } = await source('../src/views/MedicineUploadView.vue')
const { default: SupplementUpload } = await source('../src/views/SupplementUploadView.vue')
const { useMedicineFlowStore } = await source('../src/stores/medicineFlow.ts')
const { useSupplementFlowStore } = await source('../src/stores/supplementFlow.ts')
const drugDraft = JSON.parse(
  await readFile(new URL('../../docs/schemas/examples/04_drug_draft.json', import.meta.url)),
)
const supplementDraft = JSON.parse(
  await readFile(new URL('../../docs/schemas/examples/04_supplement_draft.json', import.meta.url)),
)
const image = { image_id: 'img-01', quality_status: 'accepted' }
const drafts = {
  medicine: {
    ...drugDraft,
    source_images: [image],
    rows: drugDraft.rows.filter((row) => row.source_image_id === 'img-01'),
  },
  supplement: {
    ...supplementDraft,
    source_images: [image],
    nutrients: supplementDraft.nutrients.filter((row) => row.source_image_id === 'img-01'),
  },
}
function node(type, text = '') {
  return {
    type,
    text,
    props: {},
    children: [],
    parent: null,
    showModal() {
      this.open = true
    },
    close() {
      this.open = false
    },
  }
}
const renderer = vue.createRenderer({
  createElement: (type) => node(type),
  createText: (text) => node('#text', text),
  createComment: (text) => node('#comment', text),
  setText: (target, text) => {
    target.text = text
  },
  setElementText: (target, text) => {
    target.text = text
    target.children = []
  },
  patchProp: (target, key, _old, value) => {
    target.props[key] = value
  },
  insert(target, parent, anchor = null) {
    if (target.parent) target.parent.children.splice(target.parent.children.indexOf(target), 1)
    target.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(target)
    else parent.children.splice(index, 0, target)
  },
  remove(target) {
    target.parent?.children.splice(target.parent.children.indexOf(target), 1)
    target.parent = null
  },
  parentNode: (target) => target.parent,
  nextSibling: (target) =>
    target.parent?.children[target.parent.children.indexOf(target) + 1] ?? null,
})
function descendants(root) {
  return [root, ...root.children.flatMap(descendants)]
}
function text(root) {
  return root.text + root.children.map(text).join('')
}
function loader(root) {
  return descendants(root).filter((item) => item.props.class === 'recognition-loading')
}
function mount(kind) {
  const root = node('root')
  const app = renderer.createApp(kind === 'medicine' ? MedicineUpload : SupplementUpload)
  app.component('RouterLink', {
    setup:
      (_, { slots }) =>
      () =>
        vue.h('a', slots.default?.()),
  })
  const exposed = app.mount(root)
  const file = new File(['image'], `${kind}.png`, { type: 'image/png' })
  if (kind === 'medicine')
    exposed.selectedImages = [{ id: 1, file, previewUrl: 'blob:medicine', isLoaded: true }]
  else {
    exposed.category = '鈣'
    exposed.productName = '我的鈣片'
    exposed.images = [{ id: 1, file, kind: 'nutrition', url: 'blob:supplement', loaded: true }]
  }
  return {
    root,
    exposed,
    unmount: () => app.unmount(),
    start: () => (kind === 'medicine' ? exposed.startRecognition() : exposed.recognize()),
    isBusy: () => (kind === 'medicine' ? exposed.isUploading : exposed.busy),
    errors: () => (kind === 'medicine' ? exposed.errorMessages.join('；') : exposed.error),
    review: () => (kind === 'medicine' ? exposed.goToReview() : exposed.review()),
  }
}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
beforeEach(() => {
  pinia.setActivePinia(pinia.createPinia())
  navigation = []
  guards = []
})
for (const kind of ['medicine', 'supplement']) {
  test(`${kind}: real loading component appears immediately, prevents duplicates, then preserves the review flow`, async () => {
    const pending = deferred()
    let count = 0
    request = () => {
      count++
      return pending.promise
    }
    const view = mount(kind)
    await vue.nextTick()
    assert.equal(loader(view.root).length, 0)
    const running = view.start()
    assert.equal(view.isBusy(), true) // Set before the first await.
    await vue.nextTick()
    assert.equal(loader(view.root).length, 1)
    assert.equal(loader(view.root)[0].props.role, 'status')
    assert.match(text(loader(view.root)[0]), /辨識中…正在讀取照片中的資訊…/)
    const startButton = descendants(view.root).find(
      (item) => item.type === 'button' && text(item).trim() === '開始辨識',
    )
    assert.equal(startButton.props.disabled, true)
    await view.start()
    assert.equal(count, 1)
    assert.equal(guards[0](), false)
    // Even after HTTP response arrives, loading continues until its JSON body is read.
    const body = deferred()
    const decoding = deferred()
    pending.resolve({
      ok: true,
      json: () => {
        decoding.resolve()
        return body.promise
      },
    })
    await decoding.promise
    assert.equal(view.isBusy(), true)
    assert.equal(loader(view.root).length, 1)
    body.resolve(structuredClone(drafts[kind]))
    await running
    await vue.nextTick()
    assert.equal(view.isBusy(), false)
    assert.equal(loader(view.root).length, 0)
    assert.ok(descendants(view.root).some((item) => item.type === 'dialog' && item.open))
    assert.deepEqual(navigation, []) // Keep the existing other-batch dialog.
    await view.review()
    assert.deepEqual(navigation, [kind === 'medicine' ? '/medicine-review' : '/supplement-review'])
    const store =
      kind === 'medicine' ? useMedicineFlowStore().drugBatches : useSupplementFlowStore().products
    assert.equal(store.length, 1)
    view.unmount()
  })
  test(`${kind}: API failure clears animation, keeps images and existing error details, and permits retry`, async () => {
    const pending = deferred()
    request = () => pending.promise
    const view = mount(kind)
    const running = view.start()
    await vue.nextTick()
    assert.equal(loader(view.root).length, 1)
    pending.resolve(
      Response.json(
        { error: { code: 'extraction_failed', message: '辨識服務暫時無法使用' } },
        { status: 502 },
      ),
    )
    await running
    await vue.nextTick()
    assert.equal(view.isBusy(), false)
    assert.equal(loader(view.root).length, 0)
    assert.match(view.errors(), /辨識服務暫時無法使用/)
    const images = kind === 'medicine' ? view.exposed.selectedImages : view.exposed.images
    assert.equal(images.length, 1)
    assert.equal(view.exposed.canUpload, true)
    const retry = deferred()
    request = () => retry.promise
    const retrying = view.start()
    await vue.nextTick()
    assert.equal(loader(view.root).length, 1)
    retry.resolve(Response.json(drafts[kind]))
    await retrying
    await vue.nextTick()
    assert.equal(loader(view.root).length, 0)
    assert.equal(view.isBusy(), false)
    view.unmount()
  })
  test(`${kind}: invalid recognition data clears animation without saving a batch`, async () => {
    request = async () => Response.json({})
    const view = mount(kind)
    await view.start()
    await vue.nextTick()
    assert.equal(loader(view.root).length, 0)
    assert.ok(view.errors())
    assert.equal(view.exposed.canUpload, true)
    assert.equal(useMedicineFlowStore().drugBatches.length, 0)
    assert.equal(useSupplementFlowStore().products.length, 0)
    view.unmount()
  })
}
test('two mounted pages share only presentation; loading lasts beyond one animation cycle and ends independently', async () => {
  const pendingMedicine = deferred()
  const pendingSupplement = deferred()
  request = (path) =>
    path === '/api/drug-drafts' ? pendingMedicine.promise : pendingSupplement.promise
  const medicine = mount('medicine')
  const supplement = mount('supplement')
  const medicineRun = medicine.start()
  await vue.nextTick()
  assert.equal(loader(medicine.root).length, 1)
  assert.equal(loader(supplement.root).length, 0)
  const supplementRun = supplement.start()
  await new Promise((resolve) => setTimeout(resolve, 2600))
  assert.equal(loader(medicine.root).length, 1)
  assert.equal(loader(supplement.root).length, 1)
  pendingSupplement.resolve(Response.json(drafts.supplement))
  await supplementRun
  await vue.nextTick()
  assert.equal(loader(supplement.root).length, 0)
  assert.equal(loader(medicine.root).length, 1)
  pendingMedicine.reject(new Error('network unavailable'))
  await medicineRun
  await vue.nextTick()
  assert.equal(loader(medicine.root).length, 0)
  assert.equal(loader(supplement.root).length, 0)
  assert.equal(useMedicineFlowStore().drugBatches.length, 0)
  assert.equal(useSupplementFlowStore().products.length, 1)
  assert.ok(medicine.errors())
  medicine.unmount()
  supplement.unmount()
})
test('animation style compiles, moves only the magnifier and supports reduced motion', async () => {
  const file = new URL('../src/components/RecognitionLoading.vue', import.meta.url)
  const { descriptor } = parse(await readFile(file, 'utf8'))
  assert.equal(descriptor.script, null)
  assert.equal(descriptor.scriptSetup, null) // No shared state or completion timer.
  const css = compileStyle({
    source: descriptor.styles[0].content,
    id: 'loading-test',
    scoped: true,
  })
  assert.deepEqual(css.errors, [])
  assert.match(css.code, /animation: recognition-patrol-loading-test 2\.5s ease-in-out infinite/)
  assert.match(css.code, /prefers-reduced-motion: reduce/)
  assert.match(css.code, /animation: none/)
  assert.doesNotMatch(
    css.code.match(/\.recognition-document[^}]+}/)?.[0] ?? '',
    /animation|transform/,
  )
})
