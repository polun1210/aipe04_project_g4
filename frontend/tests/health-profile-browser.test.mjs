import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { access, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'

// Run the real Vue app in Chrome. Inject only the service boundary: native inputs,
// button activation, submit events, validation, focus and routing stay unmodified.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const origin = 'http://127.0.0.1:4178'
const artifacts = await mkdtemp(join(tmpdir(), 'health-profile-review-browser-'))
const sockets = []
let vite, chrome, chromePort
let chromeOutput = ''
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
async function until(check) {
  const end = Date.now() + 15000
  while (Date.now() < end) {
    const result = await check()
    if (result) return result
    await wait(50)
  }
  throw new Error('Browser condition timed out')
}
async function chromeExecutable() {
  const candidates = process.env.CHROME_PATH
    ? [process.env.CHROME_PATH]
    : process.platform === 'win32'
      ? [
          'C:/Program Files/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
        ]
      : ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']
  for (const path of candidates) {
    try {
      await access(path)
      return path
    } catch {
      /* Try the next installation; missing Chrome must fail, never skip. */
    }
  }
  throw new Error('Chrome is required. Set CHROME_PATH to its executable.')
}
async function connect(url) {
  const ws = new WebSocket(url)
  sockets.push(ws)
  await new Promise((resolve, reject) => {
    ws.onopen = resolve
    ws.onerror = reject
  })
  let sequence = 0
  const pending = new Map(),
    handlers = new Map()
  ws.onclose = ({ code, reason }) => {
    for (const task of pending.values()) {
      clearTimeout(task.timer)
      task.reject(new Error(`Chrome connection closed (${code}: ${reason}). ${chromeOutput}`))
    }
    pending.clear()
  }
  ws.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    if (message.id) {
      const task = pending.get(message.id)
      if (!task) return
      clearTimeout(task.timer)
      pending.delete(message.id)
      if (message.error) task.reject(new Error(JSON.stringify(message.error)))
      else task.resolve(message.result)
    } else {
      for (const handler of handlers.get(message.method) ?? []) handler(message.params)
    }
  }
  const page = {
    send(method, params = {}) {
      const id = ++sequence
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id)
          reject(new Error(`CDP timed out: ${method}`))
        }, 15000)
        pending.set(id, { resolve, reject, timer })
        ws.send(JSON.stringify({ id, method, params }))
      })
    },
    on(event, callback) {
      handlers.set(event, [...(handlers.get(event) ?? []), callback])
    },
    async eval(expression) {
      const result = await page.send('Runtime.evaluate', {
        expression,
        awaitPromise: true,
        returnByValue: true,
      })
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails))
      return result.result.value
    },
    async click(selector, disabled = false) {
      const point = await page.eval(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error('Missing click target');
        el.scrollIntoView({block: 'center'});
        const rect = el.getBoundingClientRect();
        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2,
          disabled: el.disabled, height: rect.height};
      })()`)
      assert.equal(point.disabled, disabled, `${selector}: disabled state`)
      await page.send('Input.dispatchMouseEvent', {
        type: 'mousePressed',
        x: point.x,
        y: point.y,
        button: 'left',
        clickCount: 1,
      })
      await page.send('Input.dispatchMouseEvent', {
        type: 'mouseReleased',
        x: point.x,
        y: point.y,
        button: 'left',
        clickCount: 1,
      })
    },
    async fill(selector, value) {
      await page.eval(
        `document.querySelector(${JSON.stringify(selector)}).focus(); document.querySelector(${JSON.stringify(selector)}).select()`,
      )
      if (value) await page.send('Input.insertText', { text: value })
      else {
        await page.send('Input.dispatchKeyEvent', {
          type: 'keyDown',
          key: 'Backspace',
          code: 'Backspace',
          windowsVirtualKeyCode: 8,
        })
        await page.send('Input.dispatchKeyEvent', {
          type: 'keyUp',
          key: 'Backspace',
          code: 'Backspace',
          windowsVirtualKeyCode: 8,
        })
      }
    },
  }
  return page
}

before(async () => {
  const executable = await chromeExecutable()
  vite = spawn(
    process.execPath,
    [
      join(frontend, 'node_modules/vite/bin/vite.js'),
      '--host',
      '127.0.0.1',
      '--port',
      '4178',
      '--strictPort',
    ],
    { cwd: frontend, windowsHide: true, stdio: 'pipe' },
  )
  let output = ''
  vite.stdout.on('data', (chunk) => {
    output += chunk
  })
  vite.stderr.on('data', (chunk) => {
    output += chunk
  })
  await until(async () => {
    if (vite.exitCode !== null) throw new Error(`Vite failed: ${output}`)
    try {
      return (await fetch(origin)).ok
    } catch {
      return false
    }
  })
  chrome = spawn(
    executable,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--remote-debugging-address=127.0.0.1',
      '--remote-debugging-port=0',
      `--user-data-dir=${join(artifacts, 'profile')}`,
      'about:blank',
    ],
    { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] },
  )
  chrome.stderr.on('data', (chunk) => {
    chromeOutput = (chromeOutput + chunk).slice(-8000)
  })
  console.log(`Browser: ${executable}; Node: ${process.version}; Vite: ${origin}`)
  chromePort = await until(async () => {
    if (chrome.exitCode !== null)
      throw new Error(`Chrome exited (${chrome.exitCode}). ${chromeOutput}`)
    try {
      return (await readFile(join(artifacts, 'profile/DevToolsActivePort'), 'utf8')).split('\n')[0]
    } catch {
      return false
    }
  })
})
after(() => {
  for (const socket of sockets) socket.close()
  chrome?.kill()
  vite?.kill()
  console.log(`Browser screenshots: ${artifacts}`)
})

for (const width of [1200, 390]) {
  for (const kind of ['initial', 'settings']) {
    test(`${kind} ${width}px: native save button validates, focuses errors, blocks invalid API calls and preserves service states`, async () => {
      const info = await (
        await fetch(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method: 'PUT' })
      ).json()
      const page = await connect(info.webSocketDebuggerUrl)
      const browserErrors = [],
        apiRequests = []
      page.on('Runtime.exceptionThrown', (error) => browserErrors.push(error))
      page.on('Network.requestWillBeSent', ({ request }) => {
        if (request.url.startsWith(`${origin}/api/`)) apiRequests.push(request.url)
      })
      await page.send('Runtime.enable')
      await page.send('Network.enable')
      await page.send('Page.enable')
      await page.send('Emulation.setDeviceMetricsOverride', {
        width,
        height: 900,
        deviceScaleFactor: 1,
        mobile: width < 500,
      })
      const path = kind === 'initial' ? '/health-profile' : '/settings'
      const submit = 'main button[type="submit"]'
      const conditions = kind === 'initial' ? 'initial-conditions' : 'profile-conditions'
      const saveLabel = kind === 'initial' ? '儲存並開始使用' : '儲存變更'
      await page.send('Page.navigate', { url: `${origin}${path}` })
      await until(() => page.eval(`!!document.querySelector(${JSON.stringify(submit)})`))
      assert.equal(
        await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
        true,
      )
      assert.match(await page.eval('document.querySelector("main").textContent'), /尚未開放/)
      await page.click(submit, true)
      assert.equal(await page.eval('!!document.querySelector("main [role=alert]")'), false)

      // Test-only service: held promises make loading/saving states observable.
      // Never add this provider or fabricated success to production code.
      await page.eval(`(async () => {
        const app = document.querySelector('#app').__vue_app__;
        const router = app.config.globalProperties.$router;
        await router.push('/');
        const {healthProfileGatewayKey} = await import('/src/services/healthProfileGateway.ts');
        const {ApiError} = await import('/src/api/client.ts');
        const state = window.__profileTest = {loads: 0, saves: [], submits: []};
        document.addEventListener('submit', event => state.submits.push({trusted: event.isTrusted, label: event.submitter?.textContent.trim()}), true);
        state.profile = {birth_year: 1954, birth_month: 3, sex: 'male', conditions: {selected: [], none_selected: true}};
        state.fail = () => state.rejectSave(new ApiError(503, {error: {code: 'unavailable', message: '儲存失敗，請稍後重試。'}}));
        const save = value => {state.saves.push(structuredClone(value)); return new Promise((resolve, reject) => {state.resolveSave = resolve; state.rejectSave = reject})};
        app.provide(healthProfileGatewayKey, {available: true,
          loadProfile: () => {state.loads++; return new Promise((resolve, reject) => {state.resolveLoad = resolve; state.rejectLoad = reject})},
          saveInitialConditions: save, saveProfile: save});
        await router.push(${JSON.stringify(path)});
      })()`)
      await until(() => page.eval(`!!document.querySelector(${JSON.stringify(submit)})`))
      if (kind === 'settings') {
        await until(() => page.eval('window.__profileTest.loads === 1'))
        await page.click(submit, true)
        assert.equal(await page.eval('window.__profileTest.submits.length'), 0)
        await page.eval('window.__profileTest.rejectLoad(new Error("load failed"))')
        await until(() => page.eval('!!document.querySelector("main [role=alert]")'))
        assert.equal(
          await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
          true,
        )
        await page.click('main form > button[type="button"]')
        await until(() => page.eval('window.__profileTest.loads === 2'))
        assert.equal(
          await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
          true,
        )
        await page.eval('window.__profileTest.resolveLoad(window.__profileTest.profile)')
        await until(() => page.eval(`!document.querySelector(${JSON.stringify(submit)}).disabled`))
        await page.fill('#birth-year', '')
        await page.fill('#birth-month', '')
        await page.click(`#${conditions} input[value="none"]`)
      }
      // Both pages must allow invalid fields to be submitted through the button.
      await page.click(submit)
      await until(() =>
        page.eval(`!!document.querySelector('main div[role=alert][tabindex="-1"]')`),
      )
      const invalid = await page.eval(`(() => {
        const summary = document.querySelector('main div[role=alert][tabindex="-1"]');
        const links = [...summary.querySelectorAll('a')].map(a => a.getAttribute('href'));
        return {focused: document.activeElement === summary, links, text: summary.textContent,
          saves: window.__profileTest.saves.length, submits: window.__profileTest.submits,
          overflow: document.documentElement.scrollWidth > innerWidth};
      })()`)
      assert.equal(invalid.focused, true)
      assert.equal(invalid.saves, 0)
      assert.deepEqual(invalid.submits, [{ trusted: true, label: saveLabel }])
      assert.equal(invalid.overflow, false)
      const fields = kind === 'initial' ? [conditions] : ['birth-year', 'birth-month', conditions]
      for (const field of fields) {
        assert.ok(invalid.links.includes(`#${field}`), `${field} summary link`)
        const error = await page.eval(`(() => {
          const field = document.getElementById(${JSON.stringify(field)});
          const error = document.getElementById(${JSON.stringify(`${field}-error`)});
          return {invalid: field.getAttribute('aria-invalid'), described: field.getAttribute('aria-describedby'), text: error?.textContent, role: error?.getAttribute('role')};
        })()`)
        assert.equal(error.invalid, 'true')
        assert.ok(error.described.includes(`${field}-error`))
        assert.ok(error.text.trim())
        assert.ok(invalid.text.includes(error.text.trim()))
        assert.equal(error.role, 'alert')
      }
      const screenshot = await page.send('Page.captureScreenshot', { format: 'png' })
      await writeFile(
        join(artifacts, `${kind}-${width}-validation.png`),
        Buffer.from(screenshot.data, 'base64'),
      )

      if (kind === 'settings') {
        await page.fill('#birth-year', '1954')
        await page.fill('#birth-month', '3')
      }
      await page.click(`#${conditions} input[value="none"]`)
      await page.click(submit)
      await until(() => page.eval('window.__profileTest.saves.length === 1'))
      assert.equal(
        await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
        true,
      )
      assert.equal(
        await page.eval(`!!document.querySelector('main div[role=alert][tabindex="-1"]')`),
        false,
      )
      await page.click(submit, true)
      assert.equal(await page.eval('window.__profileTest.saves.length'), 1)
      assert.equal(await page.eval('window.__profileTest.submits.length'), 2)
      assert.equal(await page.eval('location.pathname'), path)
      assert.equal(
        await page.eval('document.querySelector("main").textContent.includes("個人資料已儲存。")'),
        false,
      )
      await page.eval('window.__profileTest.fail()')
      await until(() =>
        page.eval('document.querySelector("main").textContent.includes("儲存失敗，請稍後重試。")'),
      )
      assert.equal(
        await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
        false,
      )
      assert.equal(await page.eval('location.pathname'), path)
      await page.click(submit)
      await until(() => page.eval('window.__profileTest.saves.length === 2'))
      const expected =
        kind === 'initial'
          ? { selected: [], none_selected: true }
          : {
              birth_year: 1954,
              birth_month: 3,
              sex: 'male',
              conditions: { selected: [], none_selected: true },
            }
      assert.deepEqual(await page.eval('window.__profileTest.saves'), [expected, expected])
      await page.eval('window.__profileTest.resolveSave()')
      if (kind === 'initial')
        await until(() => page.eval('location.pathname === "/medicine-upload"'))
      else {
        await until(() =>
          page.eval('document.querySelector("main").textContent.includes("個人資料已儲存。")'),
        )
        assert.equal(await page.eval('location.pathname'), '/settings')
        assert.equal(
          await page.eval(`document.querySelector(${JSON.stringify(submit)}).disabled`),
          false,
        )
      }
      assert.deepEqual(browserErrors, [])
      assert.deepEqual(apiRequests, [])
    })
  }
}
