import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'
import { readFile } from 'node:fs/promises'

// 把純函式 TypeScript 轉成 JS 後載入，不依賴 Vue 或瀏覽器。
const source = await readFile(new URL('../src/router/authGuard.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
}).outputText
const { resolveAuthRedirect, safeRedirect } = await import(
  `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
)

const done = { user_id: 'u1', email: 'a@example.com', name: 'A', profile_completed: true }
const fresh = { ...done, profile_completed: false }
const to = (name, fullPath = `/${name}`) => ({ name, fullPath })

test('沒登入：需要登入的頁面導去 login 並帶 redirect', () => {
  for (const name of ['member-center', 'settings', 'health-profile', 'medicine-upload', 'report'])
    assert.deepEqual(resolveAuthRedirect(to(name, `/x/${name}`), null), {
      name: 'login',
      query: { redirect: `/x/${name}` },
    })
})

test('沒登入：首頁與登入頁放行', () => {
  assert.equal(resolveAuthRedirect(to('home', '/'), null), null)
  assert.equal(resolveAuthRedirect(to('login'), null), null)
})

test('登入但沒填健康資料：評估流程導去 health-profile', () => {
  for (const name of [
    'medicine-upload',
    'medicine-review',
    'supplement-upload',
    'supplement-review',
  ])
    assert.deepEqual(resolveAuthRedirect(to(name), fresh), {
      name: 'health-profile',
    })
})

test('登入但沒填健康資料：health-profile、settings、會員中心放行', () => {
  for (const name of ['health-profile', 'settings', 'member-center', 'reports'])
    assert.equal(resolveAuthRedirect(to(name), fresh), null)
})

test('登入且已填：全部放行', () => {
  for (const name of ['medicine-upload', 'supplement-review', 'report', 'settings'])
    assert.equal(resolveAuthRedirect(to(name), done), null)
})

test('已登入又進 login：依基本資料是否完成決定下一頁', () => {
  assert.deepEqual(resolveAuthRedirect(to('login'), done), { path: '/medicine-upload' })
  assert.deepEqual(resolveAuthRedirect(to('login'), fresh), { path: '/health-profile' })
})

test('redirect 只接受站內路徑，外站被擋', () => {
  assert.equal(safeRedirect('/supplement-review'), '/supplement-review')
  for (const bad of [
    '//evil.example',
    'https://evil.example',
    'javascript:alert(1)',
    '',
    undefined,
    ['/a'],
  ])
    assert.equal(safeRedirect(bad), '/medicine-upload')
})
