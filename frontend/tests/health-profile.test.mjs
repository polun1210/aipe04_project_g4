import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { beforeEach, test } from 'node:test'
import { setImmediate } from 'node:timers/promises'
import vm from 'node:vm'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

let navigation, httpCalls
const context = vm.createContext({
  console,
  fetch: () => {
    httpCalls++
    throw new Error('Unexpected HTTP request')
  },
})
const pendingModules = new Map()
const exposures = {
  HealthProfileView: 'conditions, handleSubmit, canSave, error, saving',
  SettingsView:
    'form, password, handleSubmit, handleCancel, loadProfile, canSave, error, saved, loaded, loading',
  RegisterView: 'form, handleSubmit',
}
const RouterLink = {
  props: ['to'],
  setup:
    (props, { slots }) =>
    () =>
      vue.h('a', { href: props.to }, slots.default?.()),
}
function load(id) {
  if (!pendingModules.has(id)) pendingModules.set(id, createModule(id))
  return pendingModules.get(id)
}
async function createModule(id) {
  let module
  if (!id.startsWith('file:')) {
    const exports =
      id === 'vue'
        ? { ...vue, vModelText: {}, vModelRadio: {} }
        : {
            RouterLink,
            useRouter: () => ({
              push: async (path) => {
                navigation.push(path)
              },
            }),
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
      if (exposures[name])
        source = source.replace('</script>', `\ndefineExpose({ ${exposures[name]} })\n</script>`)
      const { descriptor } = parse(source)
      if (descriptor.scriptSetup)
        source = compileScript(descriptor, {
          id: name,
          inlineTemplate: true,
          templateOptions: { compilerOptions: { hoistStatic: false } },
        }).content
      else {
        const result = compileTemplate({
          source: descriptor.template.content,
          id: name,
          compilerOptions: { hoistStatic: false },
        })
        assert.deepEqual(result.errors, [])
        source = `${result.code}\nexport default { render }`
      }
    }
    module = new vm.SourceTextModule(
      ts.transpileModule(source, {
        compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
      }).outputText,
      { context, identifier: id },
    )
  }
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
const { default: Initial } = await source('../src/views/HealthProfileView.vue')
const { default: Settings } = await source('../src/views/SettingsView.vue')
const { default: Register } = await source('../src/views/RegisterView.vue')
const { default: MemberCenter } = await source('../src/views/MemberCenterView.vue')
const { healthProfileGatewayKey } = await source('../src/services/healthProfileGateway.ts')
const { conditionsError, profileErrors, profilePayload } = await source(
  '../src/models/healthProfile.ts',
)
const { ApiError } = await source('../src/api/client.ts')
function node(type, text = '') {
  return {
    type,
    text,
    props: {},
    children: [],
    parent: null,
    focus() {
      this.focused = true
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
  patchProp: (target, key, _previous, value) => {
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
function all(root) {
  return [root, ...root.children.flatMap(all)]
}
function text(root) {
  return (root.type === '#comment' ? '' : root.text) + root.children.map(text).join('')
}
function mount(component, gateway) {
  const root = node('root')
  const app = renderer.createApp(component)
  app.component('RouterLink', RouterLink)
  if (gateway) app.provide(healthProfileGatewayKey, gateway)
  return { root, exposed: app.mount(root), unmount: () => app.unmount() }
}
function checkbox(view, value) {
  return all(view.root).find(
    (item) => item.type === 'input' && item.props.type === 'checkbox' && item.props.value === value,
  )
}
async function check(view, value, checked = true) {
  checkbox(view, value).props.onChange({ target: { checked } })
  await vue.nextTick()
}
const json = (value) => JSON.parse(JSON.stringify(value))
async function flushPromises() {
  // nextTick only drains Vue's render queue. The service mock's host Promise
  // is awaited by code in a vm realm; drain its microtasks before Vue's update.
  await setImmediate()
  await vue.nextTick()
}
const profile = {
  birth_year: 1954,
  birth_month: 3,
  sex: 'male',
  conditions: { selected: [], none_selected: true },
}
function gateway(overrides = {}) {
  return {
    available: true,
    loadProfile: async () => structuredClone(profile),
    saveProfile: async () => {},
    saveInitialConditions: async () => {},
    ...overrides,
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
  navigation = []
  httpCalls = 0
})

test('initial page renders exact choices, real labels, keyboard checkboxes and unavailable save', async () => {
  const view = mount(Initial)
  assert.match(text(view.root), /歡迎使用補藥亂吃！/)
  assert.match(text(view.root), /開始使用前，請先完成基本健康資料。/)
  assert.match(text(view.root), /是否有慢性疾病？/)
  assert.match(text(view.root), /尚未開放/)
  const checks = all(view.root).filter(
    (item) => item.type === 'input' && item.props.type === 'checkbox',
  )
  assert.deepEqual(
    checks.map((item) => item.props.value),
    ['hypertension', 't2dm', 'dyslipidemia', 'chronic_arthritis', 'chronic_insomnia', 'none'],
  )
  for (const label of [
    '高血壓',
    '第二型糖尿病',
    '高血脂',
    '慢性關節炎／長期關節疼痛',
    '慢性失眠',
    '以上皆無',
  ])
    assert.match(text(view.root), new RegExp(label))
  assert.equal(all(view.root).find((item) => item.type === 'button').props.disabled, true)
  await view.exposed.handleSubmit()
  assert.ok(all(view.root).some((item) => item.props.role === 'alert' && item.focused))
  await check(view, 'none')
  assert.equal(conditionsError(view.exposed.conditions), '')
  await view.exposed.handleSubmit()
  assert.match(view.exposed.error, /尚未開放/)
  assert.deepEqual(navigation, [])
  assert.equal(httpCalls, 0)
  view.unmount()
})

for (const [name, component, getSelection] of [
  ['initial', Initial, (v) => v.exposed.conditions],
  ['settings', Settings, (v) => v.exposed.form.conditions],
  ['register', Register, (v) => v.exposed.form.conditions],
])
  test(`${name}: shared checkbox component preserves none-selection exclusivity in both directions`, async () => {
    const view = mount(component)
    await check(view, 'hypertension')
    await check(view, 't2dm')
    assert.deepEqual(json(getSelection(view)), {
      selected: ['hypertension', 't2dm'],
      none_selected: false,
    })
    await check(view, 'none')
    assert.deepEqual(json(getSelection(view)), { selected: [], none_selected: true })
    await check(view, 'chronic_insomnia')
    assert.deepEqual(json(getSelection(view)), {
      selected: ['chronic_insomnia'],
      none_selected: false,
    })
    await check(view, 'chronic_insomnia', false)
    assert.ok(conditionsError(getSelection(view)))
    assert.equal(httpCalls, 0)
    view.unmount()
  })

test('initial save waits for real service success, blocks empty submissions and duplicate saves', async () => {
  const pending = deferred()
  const calls = []
  const view = mount(
    Initial,
    gateway({
      saveInitialConditions: (value) => {
        calls.push(json(value))
        return pending.promise
      },
    }),
  )
  await view.exposed.handleSubmit()
  assert.equal(calls.length, 0)
  await check(view, 'none')
  assert.equal(view.exposed.canSave, true)
  const saving = view.exposed.handleSubmit()
  await view.exposed.handleSubmit()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0], { selected: [], none_selected: true })
  assert.deepEqual(navigation, [])
  pending.resolve()
  await saving
  assert.deepEqual(navigation, ['/medicine-upload'])
  view.unmount()
})

test('initial save failure retains choices and never navigates to recognition', async () => {
  const view = mount(
    Initial,
    gateway({
      saveInitialConditions: async () => {
        throw new ApiError(503, {
          error: { code: 'unavailable', message: '儲存失敗，請稍後重試。' },
        })
      },
    }),
  )
  await check(view, 'hypertension')
  await view.exposed.handleSubmit()
  assert.match(view.exposed.error, /儲存失敗/)
  assert.deepEqual(navigation, [])
  assert.deepEqual(json(view.exposed.conditions.selected), ['hypertension'])
  assert.equal(view.exposed.canSave, true)
  view.unmount()
})

test('settings contains birth fields and single-choice sex radios, preserves password and blocks unavailable saving', async () => {
  const view = mount(Settings)
  for (const id of ['birth-year', 'birth-month', 'settings-password'])
    assert.ok(all(view.root).some((item) => item.props.id === id))
  const radios = all(view.root).filter((item) => item.props.type === 'radio')
  assert.deepEqual(
    radios.map((item) => item.props.value),
    ['male', 'female'],
  )
  assert.ok(radios.every((item) => item.props.name === 'profile-sex'))
  radios[0].props.onChange()
  await vue.nextTick()
  radios[1].props.onChange()
  await vue.nextTick()
  assert.equal(view.exposed.form.sex, 'female')
  assert.equal(
    all(view.root).filter((item) => item.props.type === 'radio' && item.props.checked).length,
    1,
  )
  Object.assign(view.exposed.form, { birthYear: '1954', birthMonth: '3' })
  await check(view, 'none')
  await view.exposed.handleSubmit()
  assert.equal(view.exposed.saved, false)
  assert.equal(view.exposed.canSave, false)
  assert.match(view.exposed.error, /尚未開放/)
  view.exposed.handleCancel()
  assert.deepEqual(navigation, ['/member-center'])
  assert.equal(httpCalls, 0)
  view.unmount()
})

test('settings loads profile, validates and serializes existing contract without a password', async () => {
  const calls = []
  const pending = deferred()
  const view = mount(
    Settings,
    gateway({
      saveProfile: (value) => {
        calls.push(json(value))
        return pending.promise
      },
    }),
  )
  assert.equal(view.exposed.loading, true)
  assert.equal(view.exposed.loaded, false)
  await flushPromises()
  assert.equal(view.exposed.loading, false)
  assert.equal(view.exposed.loaded, true)
  assert.equal(view.exposed.form.birthYear, '1954')
  assert.equal(view.exposed.canSave, true)
  view.exposed.password = 'not-part-of-health-data'
  view.exposed.form.birthMonth = '13'
  await view.exposed.handleSubmit()
  assert.equal(calls.length, 0)
  view.exposed.form.birthMonth = '3'
  const saving = view.exposed.handleSubmit()
  assert.equal(view.exposed.saved, false)
  assert.deepEqual(calls, [profile])
  pending.resolve()
  await saving
  assert.equal(view.exposed.saved, true)
  view.exposed.form.birthYear = '1955'
  await vue.nextTick()
  assert.equal(view.exposed.saved, false)
  assert.deepEqual(navigation, [])
  view.unmount()
})

test('settings service read/write failures do not claim success or navigate and allow retries', async () => {
  const service = gateway({
    loadProfile: async () => {
      throw new Error('load failed')
    },
  })
  const view = mount(Settings, service)
  await flushPromises()
  assert.equal(view.exposed.loaded, false)
  assert.equal(view.exposed.canSave, false)
  assert.ok(view.exposed.error)
  service.loadProfile = async () => structuredClone(profile)
  await view.exposed.loadProfile()
  service.saveProfile = async () => {
    throw new ApiError(503, { error: { code: 'unavailable', message: '儲存失敗，請稍後重試。' } })
  }
  await view.exposed.handleSubmit()
  assert.equal(view.exposed.saved, false)
  assert.equal(view.exposed.error, '儲存失敗，請稍後重試。')
  assert.equal(view.exposed.form.birthYear, '1954')
  assert.deepEqual(navigation, [])
  view.unmount()
})

test('profile validation follows existing year/month/sex and condition code contract', () => {
  const form = {
    birthYear: '1954',
    birthMonth: '3',
    sex: 'male',
    conditions: { selected: [], none_selected: true },
  }
  assert.deepEqual(json(profilePayload(form)), profile)
  for (const [key, value] of [
    ['birthYear', '1899'],
    ['birthYear', '2101'],
    ['birthMonth', '0'],
    ['birthMonth', '13'],
    ['sex', 'other'],
  ]) {
    assert.ok(profileErrors({ ...form, [key]: value })[key])
    assert.throws(() => profilePayload({ ...form, [key]: value }))
  }
  assert.ok(conditionsError({ selected: ['unrecognized'], none_selected: false }))
  assert.ok(conditionsError({ selected: ['hypertension'], none_selected: true }))
})

test('member center retains settings, reports and disabled logout; routes remain available', async () => {
  const view = mount(MemberCenter)
  const links = all(view.root)
    .filter((item) => item.type === 'a')
    .map((item) => item.props.href)
  for (const route of ['/settings', '/reports', '/medicine-upload', '/'])
    assert.ok(links.includes(route))
  assert.ok(
    all(view.root).some(
      (item) =>
        item.type === 'button' && 'disabled' in item.props && item.props.disabled !== false && text(item).includes('登出'),
    ),
  )
  const routes = await readFile(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  for (const path of ['/health-profile', '/settings', '/medicine-upload', '/supplement-upload'])
    assert.ok(routes.includes(`path: '${path}'`))
  view.unmount()
})
