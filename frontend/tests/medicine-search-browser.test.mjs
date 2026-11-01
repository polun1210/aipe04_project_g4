import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { createServer as createNetServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

// Live HTTP integration: real FastAPI catalog/lookup/products/assessment/report.
// The backend remains its existing demonstration implementation, never a medical oracle.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const artifacts = await mkdtemp(join(tmpdir(), 'medicine-search-review-browser-'))
const sockets = []
let api, vite, chrome, origin
const delay = (ms) => new Promise((done) => setTimeout(done, ms))
async function until(check) {
  const end = Date.now() + 15000
  while (Date.now() < end) {
    const value = await check()
    if (value) return value
    await delay(50)
  }
  throw new Error('Browser condition timed out')
}
async function connect(url) {
  const socket = new WebSocket(url)
  sockets.push(socket)
  await new Promise((resolve, reject) => {
    socket.onopen = resolve
    socket.onerror = reject
  })
  let sequence = 0
  const pending = new Map(),
    handlers = new Map()
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    if (message.id) {
      const task = pending.get(message.id)
      if (!task) return
      clearTimeout(task.timer)
      pending.delete(message.id)
      if (message.error) task.reject(new Error(JSON.stringify(message.error)))
      else task.resolve(message.result)
    } else for (const handler of handlers.get(message.method) ?? []) handler(message.params)
  }
  socket.onclose = () => {
    for (const task of pending.values()) {
      clearTimeout(task.timer)
      task.reject(new Error('Chrome connection closed'))
    }
    pending.clear()
  }
  const page = {
    send(method, params = {}) {
      const id = ++sequence
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id)
          reject(new Error(`CDP timeout: ${method}`))
        }, 15000)
        pending.set(id, { resolve, reject, timer })
        socket.send(JSON.stringify({ id, method, params }))
      })
    },
    on(event, handler) {
      handlers.set(event, [...(handlers.get(event) ?? []), handler])
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
      await page.eval(
        `(async () => { document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'}); await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); })()`,
      )
      const point = await page.eval(
        `(() => {const el=document.querySelector(${JSON.stringify(selector)}); if(!el)throw new Error('Missing click target'); el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,disabled:!!el.disabled};})()`,
      )
      assert.equal(point.disabled, disabled, selector)
      for (const type of ['mousePressed', 'mouseReleased'])
        await page.send('Input.dispatchMouseEvent', {
          type,
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
      else
        for (const type of ['keyDown', 'keyUp'])
          await page.send('Input.dispatchKeyEvent', {
            type,
            key: 'Backspace',
            code: 'Backspace',
            windowsVirtualKeyCode: 8,
          })
    },
    async select(selector, value) {
      await page.eval(
        `(() => {const el=document.querySelector(${JSON.stringify(selector)}); el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('change',{bubbles:true}));})()`,
      )
    },
    async screenshot(name) {
      const shot = await page.send('Page.captureScreenshot', { format: 'png' })
      await writeFile(join(artifacts, name), Buffer.from(shot.data, 'base64'))
    },
  }
  return page
}

try {
  const listener = createNetServer()
  await new Promise((resolve, reject) => {
    listener.once('error', reject)
    listener.listen(0, '127.0.0.1', resolve)
  })
  const apiPort = listener.address().port
  await new Promise((resolve, reject) =>
    listener.close((error) => (error ? reject(error) : resolve())),
  )
  const apiOrigin = `http://127.0.0.1:${apiPort}`
  const python =
    process.env.PYTHON_PATH ??
    join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
  let apiLog = ''
  api = spawn(
    python,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)],
    {
      cwd: root,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, NARRATOR: 'template', PYTHONDONTWRITEBYTECODE: '1' },
    },
  )
  api.stdout.on('data', (chunk) => {
    apiLog += chunk
  })
  api.stderr.on('data', (chunk) => {
    apiLog += chunk
  })
  await until(async () => {
    if (api.exitCode !== null) throw new Error(`FastAPI exited: ${apiLog}`)
    try {
      return (await fetch(`${apiOrigin}/api/health`)).ok
    } catch {
      return false
    }
  })
  vite = await createServer({
    root: join(root, 'frontend'),
    server: {
      host: '127.0.0.1',
      port: 0,
      proxy: { '^/api(?:/|$)': { target: apiOrigin, changeOrigin: true } },
    },
  })
  await vite.listen()
  origin = `http://127.0.0.1:${vite.httpServer.address().port}`
  const catalog = await (await fetch(`${apiOrigin}/api/catalog`)).json()
  const lookup = await (await fetch(`${apiOrigin}/api/drugs/lookup?name=a`)).json()
  const candidate = lookup.candidates[0]
  assert.ok(candidate, 'Existing backend catalog must supply a real candidate')
  const category = candidate.drug_class_codes[0]
  const different = catalog.drug_classes.find(
    (item) => !candidate.drug_class_codes.includes(item.drug_class_code),
  ).drug_class_code
  const originalDraft = JSON.parse(
    await readFile(join(root, 'docs/schemas/examples/04_drug_draft.json'), 'utf8'),
  )
  const submission = JSON.parse(
    await readFile(join(root, 'docs/schemas/examples/05a_verification_submission.json'), 'utf8'),
  )
  const supplementDraft = JSON.parse(
    await readFile(join(root, 'docs/schemas/examples/04_supplement_draft.json'), 'utf8'),
  )
  const executable =
    process.env.CHROME_PATH ??
    (process.platform === 'win32'
      ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
      : '/usr/bin/google-chrome')
  let chromeLog = ''
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
    chromeLog = (chromeLog + chunk).slice(-8000)
  })
  const chromePort = await until(async () => {
    if (chrome.exitCode !== null) throw new Error(`Chrome exited: ${chromeLog}`)
    try {
      return (await readFile(join(artifacts, 'profile/DevToolsActivePort'), 'utf8')).split('\n')[0]
    } catch {
      return false
    }
  })
  for (const width of [1200, 390]) {
    const info = await (
      await fetch(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method: 'PUT' })
    ).json()
    const page = await connect(info.webSocketDebuggerUrl),
      requests = [],
      errors = []
    page.on('Runtime.exceptionThrown', (error) => errors.push(error))
    page.on('Network.requestWillBeSent', ({ request }) => {
      if (request.url.startsWith(`${origin}/api/`)) requests.push(request)
    })
    for (const domain of ['Runtime', 'Page', 'Network']) await page.send(`${domain}.enable`)
    await page.send('Emulation.setDeviceMetricsOverride', {
      width,
      height: 900,
      deviceScaleFactor: 1,
      mobile: width < 500,
    })
    await page.send('Page.navigate', { url: `${origin}/medicine-review` })
    await until(() => page.eval('!!document.querySelector("#review-title")'))
    await page.eval(`(async()=>{
      const app=document.querySelector('#app').__vue_app__;
      const {useMedicineFlowStore}=await import('/src/stores/medicineFlow.ts');
      const {useSupplementFlowStore}=await import('/src/stores/supplementFlow.ts');
      const store=window.__medicineTest=useMedicineFlowStore(app.config.globalProperties.$pinia);
      window.__supplementTest=useSupplementFlowStore(app.config.globalProperties.$pinia);
      window.__testRouter=app.config.globalProperties.$router;
      const draft=${JSON.stringify(originalDraft)}; draft.rows=draft.rows.slice(0,1);
      store.addDrugBatch(draft.source_images.map(()=>new File(['test image'],'package.png',{type:'image/png'})),draft);
      window.__originalDrugDraft=JSON.stringify(store.drugBatches[0].draft);
    })()`)
    const classSelect = 'select[id^="medicine-class-"]',
      nameInput = 'input[id^="medicine-name-"]',
      candidateList = 'ul[id^="medicine-candidates-"]',
      candidateOption = 'li[role="option"]',
      save = 'li form button[type="submit"]',
      lock = 'li .review-row-actions input[type="checkbox"]',
      next = 'button.primary-action'
    await until(() => page.eval(`!!document.querySelector(${JSON.stringify(lock)})`))
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(lock)}).disabled`), false)
    await page.click(lock)
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(next)}).disabled`), false)
    assert.equal(requests.filter((request) => request.url.includes('/api/drugs/lookup')).length, 0)
    await page.click(lock)
    await page.click('li .review-row-actions button')
    await until(() =>
      page.eval(
        `document.querySelector(${JSON.stringify(classSelect)})?.options.length===${catalog.drug_classes.length + 2}`,
      ),
    )
    assert.equal(
      await page.eval(
        `document.querySelector(${JSON.stringify(classSelect)}).options[${catalog.drug_classes.length + 1}].textContent`,
      ),
      '其他／不確定',
    )
    await page.select(classSelect, different)
    await page.fill(nameInput, candidate.display_name_zh.slice(0, 1))
    await until(() =>
      page.eval(
        'document.querySelector("li form")?.textContent.includes("此類別找不到符合的候選藥品")',
      ),
    )
    assert.equal(
      await page.eval(`!!document.querySelector(${JSON.stringify(candidateList)})`),
      false,
    )
    await page.select(classSelect, category)
    await until(() =>
      page.eval(
        `!!document.querySelector(${JSON.stringify(candidateList)})?.querySelector(${JSON.stringify(candidateOption)})`,
      ),
    )
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(save)}).disabled`), true)
    assert.equal(
      await page.eval(
        `document.querySelector(${JSON.stringify(candidateList)}).textContent.includes('規格：') || document.querySelector(${JSON.stringify(candidateList)}).textContent.includes('許可證：')`,
      ),
      false,
    )
    assert.equal(
      await page.eval(`document.querySelector(${JSON.stringify(nameInput)}).getAttribute('role')`),
      'combobox',
    )
    assert.equal(
      await page.eval(
        `document.querySelector(${JSON.stringify(nameInput)}).getAttribute('aria-expanded')`,
      ),
      'true',
    )
    await page.screenshot(`suggestions-${width}.png`)
    await page.click(candidateOption)
    assert.equal(
      await page.eval(`document.querySelector(${JSON.stringify(nameInput)}).value`),
      candidate.display_name_zh,
    )
    assert.equal(
      await page.eval(`!!document.querySelector(${JSON.stringify(candidateList)})`),
      false,
    )
    await page.click(save)
    await page.click(lock)
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(next)}).disabled`), false)
    await page.screenshot(`normal-${width}.png`)
    await page.click(lock)
    await until(() => page.eval('!window.__medicineTest.medicines[0].isLocked'))
    await page.click('li .review-row-actions button')
    await page.select(classSelect, 'other_uncertain')
    const lookupCount = requests.filter((request) =>
      request.url.includes('/api/drugs/lookup'),
    ).length
    await page.fill(nameInput, '　 ')
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(save)}).disabled`), true)
    await page.fill(nameInput, '其他待確認藥品')
    await delay(400)
    assert.equal(
      requests.filter((request) => request.url.includes('/api/drugs/lookup')).length,
      lookupCount,
    )
    assert.equal(
      await page.eval(`!!document.querySelector(${JSON.stringify(candidateList)})`),
      false,
    )
    await page.click(save)
    await page.click(lock)
    assert.equal(await page.eval('window.__medicineTest.medicines[0].selectedMedicine'), null)
    assert.equal(await page.eval('window.__medicineTest.allConfirmed'), true)
    assert.match(
      await page.eval('document.querySelector(".review-progress").textContent'),
      /1 \/ 1/,
    )
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(next)}).disabled`), false)
    await page.screenshot(`uncertain-${width}.png`)
    await page.eval(`(async()=>{
      const data=${JSON.stringify(submission)};
      window.__supplementTest.products.push({id:crypto.randomUUID(),draft:{...${JSON.stringify(supplementDraft)},source_images:[]},files:[],name:data.product_name,servingSize:data.serving_info.serving_size,doseUnit:data.serving_info.dose_unit,frequency:data.user_intake.frequency_type,times:data.user_intake.times_per_day,amount:data.user_intake.amount_per_time,
      rows:data.nutrients.map(n=>{const value={choice:n.standard_code??n.scope_status,amount:n.per_serving??null,unit:n.unit??'',form:n.nutrient_form_code??'',elemental:n.stated_elemental_amount??null}; return {id:crypto.randomUUID(),rowId:n.row_id,rawName:null,sourceImageId:null,locked:true,editing:false,isNew:false,error:'',value,edit:{...value}}}),savedPayload:null,savedProductId:null});
      await window.__testRouter.push('/supplement-review');
    })()`)
    await until(() =>
      page.eval(
        '!!document.querySelector("main form button[type=submit]") && !document.querySelector("main").textContent.includes("正在載入營養素選項")',
      ),
    )
    assert.equal(
      await page.eval('document.querySelector("main form button[type=submit]").disabled'),
      false,
    )
    assert.equal(requests.filter((request) => request.method === 'POST').length, 0)
    assert.equal(
      await page.eval(
        'JSON.stringify(window.__medicineTest.drugBatches[0].draft)===window.__originalDrugDraft',
      ),
      true,
    )
    assert.equal(
      await page.eval('window.__medicineTest.drugBatches[0].files[0].name'),
      'package.png',
    )
    await page.eval('window.__testRouter.push("/medicine-review")')
    await until(() => page.eval('!!document.querySelector("li .review-row-actions button")'))
    await page.click(lock)
    await until(() => page.eval('!window.__medicineTest.medicines[0].isLocked'))
    await page.click('li .review-row-actions button')
    await page.select(classSelect, category)
    await page.fill(nameInput, candidate.display_name_zh.slice(0, 1))
    await until(() =>
      page.eval(
        `!!document.querySelector(${JSON.stringify(candidateList)})?.querySelector(${JSON.stringify(candidateOption)})`,
      ),
    )
    await page.eval(`document.querySelector(${JSON.stringify(nameInput)}).focus()`)
    for (const [key, code] of [
      ['ArrowDown', 40],
      ['Enter', 13],
    ]) {
      await page.send('Input.dispatchKeyEvent', {
        type: 'keyDown',
        key,
        windowsVirtualKeyCode: code,
      })
      await page.send('Input.dispatchKeyEvent', { type: 'keyUp', key, windowsVirtualKeyCode: code })
    }
    assert.equal(
      await page.eval(`document.querySelector(${JSON.stringify(nameInput)}).value`),
      candidate.display_name_zh,
    )
    assert.equal(
      await page.eval(`!!document.querySelector(${JSON.stringify(candidateList)})`),
      false,
    )
    await page.click(save)
    await page.click(lock)
    await page.eval('window.__testRouter.push("/supplement-review")')
    await until(() =>
      page.eval(
        '!!document.querySelector("main form button[type=submit]") && !document.querySelector("main form button[type=submit]").disabled',
      ),
    )
    await page.click('main form button[type=submit]')
    await until(() =>
      page.eval(
        'location.pathname.startsWith("/report/") && document.querySelector("main").textContent.includes("列印／另存 PDF")',
      ),
    )
    assert.ok(
      (await page.eval('document.querySelector("main").textContent')).includes(
        candidate.display_name_zh,
      ),
    )
    const assessmentRequest = requests.find(
      (request) =>
        request.method === 'POST' && new URL(request.url).pathname === '/api/assessments',
    )
    assert.equal(
      JSON.parse(assessmentRequest.postData).drugs.selected[0].name,
      candidate.display_name_zh,
    )
    assert.equal(await page.eval('window.__medicineTest.medicines.length'), 0)
    assert.equal(await page.eval('document.documentElement.scrollWidth>innerWidth'), false)
    assert.deepEqual(errors, [])
    await page.screenshot(`report-${width}.png`)
    console.log(`PASS ${width}px: recognition, search, uncertain review, locks and report`)
  }
  console.log(`Browser artifacts: ${artifacts}`)
} finally {
  for (const socket of sockets) socket.close()
  chrome?.kill()
  await vite?.close()
  api?.kill()
}
