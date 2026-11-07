import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { setImmediate } from 'node:timers/promises'
import { createPinia, setActivePinia } from 'pinia'
import ts from 'typescript'

const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const compile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const apiUrl = moduleUrl('export const api = {}; export const notifyCompletion = async () => {}')
const { api } = await import(apiUrl)
const profilesUrl = moduleUrl(compile(await readFile(new URL('../src/profiles.ts', import.meta.url), 'utf8')))
const proposalUrl = moduleUrl(compile(await readFile(new URL('../src/proposal.ts', import.meta.url), 'utf8')))
const storeSource = compile(await readFile(new URL('../src/stores/app.ts', import.meta.url), 'utf8'))
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replaceAll("from 'pinia'", `from '${import.meta.resolve('pinia')}'`)
  .replaceAll("from '../api'", `from '${apiUrl}'`)
  .replaceAll("from '../profiles'", `from '${profilesUrl}'`)
  .replaceAll("from '../proposal'", `from '${proposalUrl}'`)
const { useAppStore } = await import(moduleUrl(storeSource))
let subscriptions, requests
const responses = {
  'app.initialize': { firstLaunch: false },
  'preset.list': [{ id: 'by-type', name: '按类型整理' }],
  'settings.get': { theme: 'dark', defaultTargetFolder: '~/Documents/整理' },
  'profile.list': [], 'history.list': [], 'quarantine.list': [],
}
beforeEach(() => {
  setActivePinia(createPinia())
  subscriptions = 0
  requests = []
  api.onEvent = () => { subscriptions++; return () => {} }
  api.request = async method => { requests.push(method); return responses[method] }
})
function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('startup is visible before the first initialization call', () => {
  const store = useAppStore()
  assert.equal(store.startupState, 'loading')
  assert.equal(store.engineReady, false)
})
test('delayed startup stays loading and duplicate requests are ignored', async () => {
  const gate = deferred()
  api.request = async method => { requests.push(method); await gate.promise; return responses[method] }
  const store = useAppStore()
  const pending = store.initialize()
  await store.initialize()
  assert.equal(requests.length, 4)
  assert.equal(store.startupState, 'loading')
  assert.equal(store.engineReady, false)
  gate.resolve()
  await pending
  assert.equal(store.startupState, 'ready')
  assert.equal(store.engineReady, true)
  assert.equal(store.presets.length, 1)
})
test('home is not revealed until history and quarantine finish loading', async () => {
  const gate = deferred()
  api.request = async method => {
    if (['history.list', 'quarantine.list'].includes(method)) await gate.promise
    return responses[method]
  }
  const store = useAppStore()
  const pending = store.initialize()
  await setImmediate()
  assert.equal(store.startupState, 'loading')
  assert.equal(store.engineReady, false)
  gate.resolve()
  await pending
  assert.equal(store.startupState, 'ready')
})
test('failed initialization can be retried without duplicate event subscriptions', async () => {
  let fail = true
  api.request = async method => {
    if (fail && method === 'app.initialize') throw new Error('模拟引擎启动失败')
    return responses[method]
  }
  const store = useAppStore()
  await store.initialize()
  assert.equal(store.startupState, 'error')
  assert.equal(store.engineReady, false)
  assert.match(store.startupError, /模拟引擎启动失败/)
  fail = false
  await store.initialize()
  assert.equal(store.startupState, 'ready')
  assert.equal(store.startupError, undefined)
  assert.equal(subscriptions, 1)
})
test('initializing an already ready app does not restart it', async () => {
  const store = useAppStore()
  await store.initialize()
  const count = requests.length
  await store.initialize()
  assert.equal(requests.length, count)
  assert.equal(subscriptions, 1)
})
test('first launch enters onboarding only after loading completes', async () => {
  api.request = async method => method === 'app.initialize' ? { firstLaunch: true } : responses[method]
  const store = useAppStore()
  await store.initialize()
  assert.equal(store.startupState, 'ready')
  assert.equal(store.view, 'onboarding')
})
test('HTML contains an accessible O placeholder before the app module', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  assert.ok(html.indexOf('class="startup-screen"') < html.indexOf('src="/src/main.ts"'))
  assert.match(html, /class="startup-screen" role="status" aria-busy="true"/)
  assert.match(html, /class="startup-o"[\s\S]*?<ellipse/)
  assert.match(html, /href="\/src\/startup.css"/)
  const css = await readFile(new URL('../src/startup.css', import.meta.url), 'utf8')
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none/)
})

test('first paint and Vue loading O share the active icon blue gradient', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  const vue = await readFile(new URL('../src/components/StartupLoading.vue', import.meta.url), 'utf8')
  const css = await readFile(new URL('../src/startup.css', import.meta.url), 'utf8')
  for (const markup of [html, vue]) {
    assert.match(markup, /<linearGradient[^>]*x1="27" y1="19" x2="85" y2="93"/)
    assert.match(markup, /<stop class="o-light"\s*\/><stop class="o-mid" offset="0.5"\s*\/><stop class="o-deep" offset="1"\s*\/>/)
    assert.match(markup, /<ellipse[^>]*stroke="url\(#startup-o-(?:initial|live)\)"/)
  }
  for (const [name, color] of [['light', '#6eb8fd'], ['mid', '#3189fd'], ['deep', '#013dcd']]) {
    assert.ok(css.includes(`--startup-o-${name}: ${color};`))
    assert.ok(css.includes(`.o-${name} { stop-color: var(--startup-o-${name}); }`))
  }
  assert.match(css, /--startup-glow: 49 137 253;/)
  assert.doesNotMatch(css, /#79e6da|#16796f|121 230 218/)
  assert.match(css, /startup-screen--failed \.startup-o ellipse \{ stroke: currentColor; \}/)
})
