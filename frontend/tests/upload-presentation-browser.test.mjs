import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { access, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'

// Run with: node --test tests/upload-presentation-browser.test.mjs
// Run the real Vue app in Edge. Inject only the service boundary: native inputs,
// button activation, submit events, validation, focus and routing stay unmodified.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const origin = 'http://127.0.0.1:4189'
const artifacts = await mkdtemp(join(tmpdir(), 'upload-review-browser-'))
const sockets = []
let vite, edge, edgePort
let edgeOutput = ''
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
async function edgeExecutable() {
  const candidates = process.env.EDGE_PATH
    ? [process.env.EDGE_PATH]
    : process.platform === 'win32'
      ? [
          'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
          'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        ]
      : ['/usr/bin/microsoft-edge', '/usr/bin/microsoft-edge-stable']
  for (const path of candidates) {
    try {
      await access(path)
      return path
    } catch {
      /* Try the next installation; missing Edge must fail, never skip. */
    }
  }
  throw new Error('Edge is required. Set EDGE_PATH to its executable.')
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
      task.reject(new Error(`Edge connection closed (${code}: ${reason}). ${edgeOutput}`))
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
  const executable = await edgeExecutable()
  vite = spawn(
    process.execPath,
    [
      join(frontend, 'node_modules/vite/bin/vite.js'),
      '--host',
      '127.0.0.1',
      '--port',
      '4189',
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
  edge = spawn(
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
  edge.stderr.on('data', (chunk) => {
    edgeOutput = (edgeOutput + chunk).slice(-8000)
  })
  console.log(`Browser: ${executable}; Node: ${process.version}; Vite: ${origin}`)
  edgePort = await until(async () => {
    if (edge.exitCode !== null)
      throw new Error(`Edge exited (${edge.exitCode}). ${edgeOutput}`)
    try {
      return (await readFile(join(artifacts, 'profile/DevToolsActivePort'), 'utf8')).split('\n')[0]
    } catch {
      return false
    }
  })
})
after(() => {
  for (const socket of sockets) socket.close()
  edge?.kill()
  vite?.kill()
  console.log(`Browser screenshots: ${artifacts}`)
})

for (const width of [1200, 390]) {
  for (const kind of ['medicine', 'supplement']) {
    test(`${kind} ${width}px: privacy placement, native file control and centered loading with failure/retry/success`, async () => {
      const info = await (
        await fetch(`http://127.0.0.1:${edgePort}/json/new?about:blank`, { method: 'PUT' })
      ).json()
      const page = await connect(info.webSocketDebuggerUrl)
      const errors = [], requests = [], held = []
      page.on('Runtime.exceptionThrown', (error) => errors.push(error))
      await page.send('Runtime.enable')
      await page.send('Page.enable')
      await page.send('Emulation.setDeviceMetricsOverride', {
        width, height: 844, deviceScaleFactor: 1, mobile: width < 500,
      })
      // Hold API requests at the service boundary; never call a real recognition provider.
      page.on('Fetch.requestPaused', ({ requestId, request }) => {
        requests.push(request)
        held.push(requestId)
      })
      await page.send('Fetch.enable', { patterns: [{ urlPattern: `${origin}/api/*` }] })
      await page.send('Page.navigate', { url: `${origin}/${kind}-upload` })
      await until(() => page.eval('!!document.querySelector("main .primary-action")'))
      const privacy = await page.eval(`(() => {
        const heading = document.querySelector('main h1');
        const next = heading.nextElementSibling;
        return {title: heading.textContent, role: next.getAttribute('role'), text: next.textContent,
          sideNote: !!document.querySelector('.guide-privacy')};
      })()`)
      if (kind === 'medicine') {
        assert.equal(privacy.title, '先上傳你的處方箋照片')
        assert.equal(privacy.role, 'alert')
        assert.equal(privacy.text, '上傳前，記得遮住姓名等不必要的個人資訊。')
        assert.equal(privacy.sideNote, false)
      } else assert.equal(privacy.sideNote, true)
      const controls = await page.eval(`Array.from(document.querySelectorAll('input[type=file]'), el => {
        const button = getComputedStyle(el, '::file-selector-button');
        return {font: getComputedStyle(el).fontSize, color: getComputedStyle(el).color,
          buttonFont: parseFloat(button.fontSize), label: el.labels[0]?.textContent.trim(),
          height: el.getBoundingClientRect().height, disabled: el.disabled};
      })`)
      assert.equal(controls.length, kind === 'medicine' ? 1 : 2)
      for (const control of controls) {
        assert.equal(control.font, '0px')
        assert.equal(control.color, 'rgba(0, 0, 0, 0)')
        assert.ok(control.buttonFont >= 14)
        assert.ok(control.label)
        assert.ok(control.height >= 44)
        assert.equal(control.disabled, false)
      }
      assert.equal(await page.eval('document.documentElement.scrollWidth > innerWidth'), false)
      const screenshot = async (label) => {
        const capture = await page.send('Page.captureScreenshot', { format: 'png' })
        await writeFile(join(artifacts, `${kind}-${width}-${label}.png`), Buffer.from(capture.data, 'base64'))
      }
      await screenshot('initial')
      if (kind === 'supplement') {
        await page.fill('#supplement-category', '鈣')
        await page.fill('#supplement-name', 'QA 測試產品')
      }
      const input = kind === 'medicine' ? '#medicine-image' : '#ingredient-images'
      const { root } = await page.send('DOM.getDocument')
      const { nodeId } = await page.send('DOM.querySelector', { nodeId: root.nodeId, selector: input })
      await page.send('DOM.setFileInputFiles', {
        nodeId, files: [join(frontend, 'public/home-supplements.webp')],
      })
      await until(() => page.eval('!document.querySelector("main .primary-action").disabled'))
      assert.equal(await page.eval('document.querySelectorAll(".preview-grid img").length'), 1)
      await page.eval(`document.querySelector(${JSON.stringify(input)}).focus()`)
      assert.equal(await page.eval(`document.activeElement.id`), input.slice(1))
      const checkCentered = async () => {
        const box = await page.eval(`(() => {
          const el = document.querySelector('.recognition-loading');
          const r = el.getBoundingClientRect();
          return {x:r.x, y:r.y, width:r.width, height:r.height,
            vw:document.documentElement.clientWidth, vh:document.documentElement.clientHeight,
            position:getComputedStyle(el).position, role:el.getAttribute('role'),
            live:el.getAttribute('aria-live'), text:el.textContent};
        })()`)
        assert.equal(box.position, 'fixed')
        assert.ok(Math.abs(box.x + box.width / 2 - box.vw / 2) <= 1, JSON.stringify(box))
        assert.ok(Math.abs(box.y + box.height / 2 - box.vh / 2) <= 1, JSON.stringify(box))
        assert.ok(box.x >= 0 && box.y >= 0)
        assert.ok(box.x + box.width <= box.vw && box.y + box.height <= box.vh)
        assert.equal(box.role, 'status')
        assert.equal(box.live, 'polite')
        assert.match(box.text, /辨識中/)
      }
      await page.click('main .primary-action')
      await until(() => held.length === 1)
      await until(() => page.eval('!!document.querySelector(".recognition-loading")'))
      await checkCentered()
      await screenshot('loading')
      await page.eval('scrollTo(0, 0)')
      await checkCentered()
      await page.eval('scrollTo(0, document.documentElement.scrollHeight)')
      await checkCentered()
      await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
      assert.equal(await page.eval('getComputedStyle(document.querySelector(".recognition-magnifier")).animationName'), 'none')
      await page.click('main .primary-action', true)
      assert.equal(requests.length, 1)
      const respond = (responseCode, body) => page.send('Fetch.fulfillRequest', {
        requestId: held.shift(), responseCode,
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
        body: Buffer.from(JSON.stringify(body)).toString('base64'),
      })
      await respond(503, { error: { code: 'unavailable', message: 'QA 辨識服務暫時無法使用' } })
      await until(() => page.eval('!document.querySelector(".recognition-loading")'))
      assert.match(await page.eval('document.querySelector("main").textContent'), /QA 辨識服務暫時無法使用/)
      assert.equal(await page.eval('document.querySelectorAll(".preview-grid img").length'), 1)
      await page.click('main .primary-action')
      await until(() => held.length === 1)
      await checkCentered()
      const file = kind === 'medicine' ? '04_drug_draft.json' : '04_supplement_draft.json'
      const draft = JSON.parse(await readFile(join(frontend, '../docs/schemas/examples', file), 'utf8'))
      draft.source_images = [{ image_id: 'img-01', quality_status: 'accepted' }]
      const rows = kind === 'medicine' ? 'rows' : 'nutrients'
      draft[rows] = draft[rows].filter((row) => row.source_image_id === 'img-01')
      await respond(200, draft)
      await until(() => page.eval('!!document.querySelector("dialog[open]")'))
      assert.equal(await page.eval('!!document.querySelector(".recognition-loading")'), false)
      assert.equal(requests.length, 2)
      assert.ok(requests.every((r) => r.method === 'POST' && r.url.endsWith(kind === 'medicine' ? '/api/drug-drafts' : '/api/supplement-drafts')))
      assert.deepEqual(errors, [])
    })
  }
}
