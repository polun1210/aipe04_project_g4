// 編譯 ReportChat.vue 的 setup()，mock askReport 後直接呼叫 ask()，驗證歷史上限與錯誤訊息。
import assert from 'node:assert/strict'
import { readFile, writeFile, rm } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'

const path = new URL('../src/components/ReportChat.vue', import.meta.url)
const { descriptor } = parse(await readFile(path, 'utf8'))
let code = compileScript(descriptor, { id: 'chat-test' }).content
code = ts.transpileModule(code, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText
code = code
  .replace(/import \{ askReport[^\n]*\n/, 'const askReport = (...a) => globalThis.__askReport(...a)\n')
  .replace(/import \{ ApiError[^\n]*\n/, 'const ApiError = globalThis.__ApiError\n')
  .replace(/import \{ ref \} from ['"]vue['"]/, "import { ref } from 'vue'")
class FakeApiError extends Error {
  constructor(code) {
    super(code)
    this.body = { error: { code } }
  }
}
globalThis.__ApiError = FakeApiError

const tmp = new URL('./.report-chat.tmp.mjs', import.meta.url)
await writeFile(tmp, code)
const { default: ReportChat } = await import(tmp.href)
await rm(tmp)

function mount(reply) {
  const calls = []
  globalThis.__askReport = async (id, question, history) => {
    calls.push({ id, question, history: [...history] })
    return reply(question)
  }
  const state = ReportChat.setup({ reportId: 'r1' }, { expose() {} })
  return { state, calls }
}

test('成功時把問答加進歷史，下一輪一併送出', async () => {
  const { state, calls } = mount((q) => ({ answer: `答：${q}` }))
  await state.ask('哪些超過上限？')
  await state.ask('再說一次')
  assert.equal(calls[0].history.length, 0)
  assert.deepEqual(calls[1].history, [
    { role: 'user', content: '哪些超過上限？' },
    { role: 'assistant', content: '答：哪些超過上限？' },
  ])
  assert.equal(state.error.value, '')
})

test('歷史最多 10 則，超過丟掉最舊的（與後端上限一致）', async () => {
  const { state, calls } = mount((q) => ({ answer: `答${q}` }))
  for (let i = 0; i < 7; i++) await state.ask(`問${i}`)
  assert.equal(state.turns.value.length, 10)
  assert.ok(calls.every((c) => c.history.length <= 10))
  assert.equal(state.turns.value[0].content, '問2')
})

test('空白問題不送出並提示', async () => {
  const { state, calls } = mount(() => ({ answer: 'x' }))
  await state.ask('   ')
  assert.equal(calls.length, 0)
  assert.equal(state.error.value, '請先輸入問題')
})

test('超過 500 字不送出', async () => {
  const { state, calls } = mount(() => ({ answer: 'x' }))
  await state.ask('問'.repeat(501))
  assert.equal(calls.length, 0)
  assert.match(state.error.value, /500/)
})

test('chat_disabled 顯示未啟用，其他錯誤顯示目前無法回答，且不進歷史', async () => {
  let code = 'chat_disabled'
  const { state } = mount(() => {
    throw new FakeApiError(code)
  })
  await state.ask('問')
  assert.equal(state.error.value, '對話功能未啟用')
  code = 'chat_failed'
  await state.ask('問')
  assert.equal(state.error.value, '目前無法回答')
  assert.equal(state.turns.value.length, 0)
  assert.equal(state.busy.value, false)
})

test('回答中再按送出不會重複請求', async () => {
  let release
  const { state, calls } = mount(() => new Promise((r) => (release = () => r({ answer: 'ok' }))))
  const first = state.ask('問')
  await state.ask('問')
  assert.equal(calls.length, 1)
  release()
  await first
})
