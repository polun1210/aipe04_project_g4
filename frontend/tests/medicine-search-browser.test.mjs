import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { createServer as createNetServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build, createServer, preview } from 'vite'

// Live HTTP integration: real FastAPI catalog/lookup/products/assessment/report.
// The backend remains its existing demonstration implementation, never a medical oracle.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const artifacts = await mkdtemp(join(tmpdir(), 'medicine-search-review-browser-'))
const sockets = []
const previewServers = []
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
        `(() => {const el=document.querySelector(${JSON.stringify(selector)}); if(!el)throw new Error('Missing click target'); el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,disabled:el.disabled};})()`,
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
      store.startEditing(store.medicines[0]);
    })()`)
    const classSelect = 'select[id^="medicine-class-"]',
      nameInput = 'input[id^="medicine-name-"]',
      candidateSelect = 'select[id^="medicine-candidates-"]',
      save = 'li form button[type="submit"]',
      lock = 'li .review-row-actions input[type="checkbox"]',
      next = 'button.primary-action'
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
    await page.fill(nameInput, candidate.display_name_zh)
    await until(() => page.eval(`!!document.querySelector(${JSON.stringify(candidateSelect)})`))
    assert.equal(
      await page.eval(
        `!!document.querySelector(${JSON.stringify(candidateSelect)}).querySelector('option[value="${candidate.active_ingredient_code}"]')`,
      ),
      false,
    )
    await page.select(classSelect, category)
    await until(() =>
      page.eval(
        `!!document.querySelector(${JSON.stringify(candidateSelect)})?.querySelector('option[value="${candidate.active_ingredient_code}"]')`,
      ),
    )
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(save)}).disabled`), true)
    assert.equal(
      await page.eval(
        `document.querySelector(${JSON.stringify(candidateSelect)}).textContent.includes('規格：') || document.querySelector(${JSON.stringify(candidateSelect)}).textContent.includes('許可證：')`,
      ),
      false,
    )
    await page.select(candidateSelect, candidate.active_ingredient_code)
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
      await page.eval(`!!document.querySelector(${JSON.stringify(candidateSelect)})`),
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
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(next)}).disabled`), true)
    assert.match(await page.eval('document.querySelector("main").textContent'), /無法產生可靠報告/)
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
    await page.click('main form button[type=submit]', true)
    await page.eval('document.querySelector("main form").requestSubmit()')
    await delay(100)
    assert.match(await page.eval('document.querySelector("main").textContent'), /無法產生可靠報告/)
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
    await page.fill(nameInput, candidate.display_name_zh)
    await until(() =>
      page.eval(
        `!!document.querySelector(${JSON.stringify(candidateSelect)})?.querySelector('option[value="${candidate.active_ingredient_code}"]')`,
      ),
    )
    await page.select(candidateSelect, candidate.active_ingredient_code)
    await page.click(save)
    await page.click(lock)
    assert.equal(await page.eval('window.__medicineTest.assessmentBlockedReason'), '')
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
    // Isolated frontend demo: the same forms, real read-only lookup, zero writes.
    const writesBeforeDemo = requests.filter((request) => request.method === 'POST').length
    await page.eval(`(() => {
      const store=window.__medicineTest; store.addMedicine();
      const row=store.medicines[0]; row.draftName='一般流程保留的藥品';
      store.saveMedicine(row,undefined,'uncertain'); store.setLocked(row,true);
      window.__normalSnapshot=JSON.stringify(store.$state);
    })()`)
    await page.eval('window.__testRouter.push("/review-demo")')
    await until(() => page.eval('!!document.querySelector(".review-demo .review-list")'))
    assert.match(
      await page.eval('document.querySelector(".review-demo").textContent'),
      /示範資料，非實際個人化評估結果/,
    )
    await page.eval(`(async()=>{
      const app=document.querySelector('[data-review-demo-host]').__vue_app__;
      const {useMedicineFlowStore}=await import('/src/stores/medicineFlow.ts');
      const {useSupplementFlowStore}=await import('/src/stores/supplementFlow.ts');
      window.__demoMedicine=useMedicineFlowStore(app.config.globalProperties.$pinia);
      window.__demoSupplement=useSupplementFlowStore(app.config.globalProperties.$pinia);
    })()`)
    assert.equal(await page.eval('window.__demoMedicine===window.__medicineTest'), false)
    for (const [index, row] of originalDraft.rows.entries()) {
      const prefix = `.review-demo .review-list > li:nth-child(${index + 1})`
      await page.click(`${prefix} .review-row-actions button`)
      const classInput = `${prefix} select[id^="medicine-class-"]`
      const name = `${prefix} input[id^="medicine-name-"]`
      if (row.scope_status === 'in_scope') {
        const results = await (
          await fetch(`${apiOrigin}/api/drugs/lookup?name=${encodeURIComponent(row.raw_name)}`)
        ).json()
        const matched = results.candidates.find(
          (item) => item.active_ingredient_code === row.active_ingredient_code,
        )
        assert.ok(matched, 'Existing sample must match the actual backend catalog')
        await until(() =>
          page.eval(`!document.querySelector(${JSON.stringify(classInput)}).disabled`),
        )
        await page.select(classInput, matched.drug_class_codes[0])
        await page.fill(name, matched.display_name_zh)
        const choices = `${prefix} select[id^="medicine-candidates-"]`
        await until(() =>
          page.eval(
            `!!document.querySelector(${JSON.stringify(choices)})?.querySelector('option[value="${matched.active_ingredient_code}"]')`,
          ),
        )
        await page.select(choices, matched.active_ingredient_code)
      } else {
        await page.select(classInput, 'other_uncertain')
        await page.fill(name, `${row.raw_name}（示範修改）`)
      }
      await page.click(`${prefix} form button[type=submit]`)
    }
    await page.click('.review-demo .bulk-controls button:first-child')
    assert.equal(await page.eval('window.__demoMedicine.allConfirmed'), true)
    assert.equal(
      await page.eval(
        'window.__demoMedicine.medicines.filter(row=>row.reviewMode==="uncertain").every(row=>row.selectedMedicine===null)',
      ),
      true,
    )
    assert.match(
      await page.eval('document.querySelector(".review-demo .review-progress").textContent'),
      /5 \/ 5/,
    )
    await page.click('.review-demo button.primary-action')
    await until(() =>
      page.eval(
        '!!document.querySelector(".review-demo .supplement-review") && !document.querySelector(".review-demo main").textContent.includes("正在載入營養素選項")',
      ),
    )
    const scopeBefore = await page.eval(
      'JSON.stringify(window.__demoSupplement.products[0].rows.filter(row=>row.value.choice==="out_of_scope"))',
    )
    assert.equal(
      await page.eval('document.querySelector(".review-demo details.out-of-scope").open'),
      false,
    )
    assert.equal(
      await page.eval('document.querySelectorAll(".review-demo .out-of-scope input").length'),
      0,
    )
    await page.fill('.review-demo input[id^="name-"]', '示範資料：編輯後的保健食品')
    // Exercise an existing nutrient edit/save, then both bulk lock directions.
    await page.eval(`(() => {
      const root=document.querySelector('.review-demo');
      [...root.querySelectorAll('button')].find(button=>button.textContent.trim()==='編輯').click();
    })()`)
    await until(() => page.eval('!!document.querySelector(".review-demo input[id^=amount-]")'))
    await page.fill('.review-demo input[id^="amount-"]', '11')
    await page.eval(
      `[...document.querySelectorAll('.review-demo button')].find(button=>button.textContent.trim()==='儲存').click()`,
    )
    await page.select('.review-demo select[id^="frequency-"]', 'daily')
    await page.select('.review-demo select[id^="times-"]', '1')
    await page.fill('.review-demo input[id^="intake-"]', '1')
    await page.eval(
      `[...document.querySelectorAll('.review-demo button')].find(button=>button.textContent.trim()==='一鍵鎖定').click()`,
    )
    await page.eval(
      `[...document.querySelectorAll('.review-demo button')].find(button=>button.textContent.trim()==='全部解除鎖定').click()`,
    )
    assert.equal(
      await page.eval('window.__demoSupplement.products[0].rows.some(row=>row.locked)'),
      false,
    )
    await page.eval(
      `[...document.querySelectorAll('.review-demo button')].find(button=>button.textContent.trim()==='一鍵鎖定').click()`,
    )
    assert.equal(
      await page.eval(
        'JSON.stringify(window.__demoSupplement.products[0].rows.filter(row=>row.value.choice==="out_of_scope"))',
      ),
      scopeBefore,
    )
    await page.click('.review-demo form button[type=submit]')
    await until(() =>
      page.eval(
        'document.querySelector(".review-demo main")?.textContent.includes("固定範例報告展示")',
      ),
    )
    assert.match(
      await page.eval('document.querySelector(".review-demo main").textContent'),
      /與剛才輸入的藥名、成分及攝取量無關/,
    )
    assert.equal(requests.filter((request) => request.method === 'POST').length, writesBeforeDemo)
    assert.equal(
      await page.eval('JSON.stringify(window.__medicineTest.$state)===window.__normalSnapshot'),
      true,
    )
    assert.equal(await page.eval('document.documentElement.scrollWidth>innerWidth'), false)
    await page.screenshot(`isolated-demo-report-${width}.png`)
    await page.eval('window.scrollTo(0, document.body.scrollHeight / 2)')
    const demoLabel = await page.eval(
      `(() => {const label=document.querySelector('.demo-label'); const r=label.getBoundingClientRect(); return {text:label.textContent,top:r.top,bottom:r.bottom};})()`,
    )
    assert.match(demoLabel.text, /示範資料，非實際個人化評估結果/)
    assert.ok(
      demoLabel.top >= 0 && demoLabel.bottom <= 900,
      'Demo warning remains visible while reading the report',
    )
    await page.click('.review-demo .demo-notice button')
    await until(() =>
      page.eval('location.pathname==="/" && !document.querySelector("[data-review-demo-host]")'),
    )
    assert.equal(await page.eval('window.__demoMedicine.medicines.length'), 0)
    assert.equal(await page.eval('window.__demoSupplement.products.length'), 0)
    assert.equal(
      await page.eval('JSON.stringify(window.__medicineTest.$state)===window.__normalSnapshot'),
      true,
    )
    await page.eval('window.__testRouter.push("/medicine-review?demo=1")')
    await until(() => page.eval('!!document.querySelector("#review-title")'))
    assert.equal(await page.eval('document.querySelector("button.primary-action").disabled'), true)
    assert.match(await page.eval('document.querySelector("main").textContent'), /無法產生可靠報告/)
    await page.eval('window.__testRouter.push("/review-demo")')
    await until(() => page.eval('!!document.querySelector(".review-demo .review-list")'))
    assert.equal(
      await page.eval('document.querySelector(".review-demo").textContent.includes("示範修改")'),
      false,
    )
    await page.click('.review-demo .demo-notice button')
    await until(() => page.eval('!document.querySelector("[data-review-demo-host]")'))
    assert.deepEqual(errors, [])
    console.log(
      `PASS ${width}px: real API regression and isolated demo editing/locks/both next buttons/fixed report/no writes/normal-state preservation/cleanup/fresh re-entry`,
    )
  }
  // Check actual production builds, not merely a mocked environment flag.
  const previousFlag = process.env.VITE_ENABLE_REVIEW_DEMO
  const previousNodeEnv = process.env.NODE_ENV
  try {
    process.env.NODE_ENV = 'production'
    for (const enabled of [false, true]) {
      process.env.VITE_ENABLE_REVIEW_DEMO = String(enabled)
      const outDir = join(artifacts, enabled ? 'enabled-build' : 'default-build')
      await build({
        root: join(root, 'frontend'),
        logLevel: 'error',
        build: { outDir, emptyOutDir: false },
      })
      const server = await preview({
        root: join(root, 'frontend'),
        logLevel: 'error',
        build: { outDir },
        preview: {
          host: '127.0.0.1',
          port: 0,
          proxy: { '^/api(?:/|$)': { target: apiOrigin, changeOrigin: true } },
        },
      })
      previewServers.push(server)
      const info = await (
        await fetch(`http://127.0.0.1:${chromePort}/json/new?about:blank`, { method: 'PUT' })
      ).json()
      const page = await connect(info.webSocketDebuggerUrl)
      await page.send('Page.enable')
      await page.send('Page.navigate', {
        url: `http://127.0.0.1:${server.httpServer.address().port}/review-demo`,
      })
      await until(() =>
        page.eval(
          enabled
            ? '!!document.querySelector(".review-demo .review-list")'
            : 'location.pathname==="/" && !!document.querySelector("#app h1")',
        ),
      )
      assert.equal(await page.eval('!!document.querySelector(".review-demo")'), enabled)
      console.log(
        `PASS production build: demo ${enabled ? 'explicitly enabled' : 'disabled by default'}`,
      )
    }
  } finally {
    if (previousFlag === undefined) delete process.env.VITE_ENABLE_REVIEW_DEMO
    else process.env.VITE_ENABLE_REVIEW_DEMO = previousFlag
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV
    else process.env.NODE_ENV = previousNodeEnv
  }
  console.log(`Browser artifacts: ${artifacts}`)
} finally {
  for (const socket of sockets) socket.close()
  chrome?.kill()
  for (const server of previewServers)
    await new Promise((resolve) => server.httpServer.close(resolve))
  await vite?.close()
  api?.kill()
}
