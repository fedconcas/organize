import type { EngineEvent, Plan, PlanItem, Preset, Profile, Proposal, ProposalCategory, RunResult, TypeRule } from './types'

type EventHandler = (event: EngineEvent) => void

function camelPlan(raw: any): Plan {
  const item = (value: any): PlanItem => ({
    itemId: value.itemId ?? value.item_id,
    sequence: value.sequence ?? value.seq,
    groupId: value.groupId ?? value.group_id,
    operation: value.operation,
    sourcePath: value.sourcePath ?? value.source_path,
    targetPath: value.targetPath ?? value.target_path,
    size: value.size,
    selected: Boolean(value.selected),
    status: value.status,
    warningCode: value.warningCode ?? value.warning_code,
    reason: value.reason,
    metadata: value.metadata ?? {},
  })
  return {
    planId: raw.planId ?? raw.plan_id,
    status: raw.status,
    createdAt: raw.createdAt ?? raw.created_at,
    expiresAt: raw.expiresAt ?? raw.expires_at,
    profile: raw.profile,
    summary: raw.summary,
    items: (raw.items ?? []).map(item),
  }
}

const sampleFiles = [
  ['2026 Annual budget.xlsx', 'Documents', 1_240_000],
  ['Scanned contract (stamped).pdf', 'Documents', 4_800_000],
  ['Quotation.pdf', 'Documents', 312_000],
  ['Meeting notes 10-02.docx', 'Documents', 86_000],
  ['IMG_2041.HEIC', 'Images', 8_420_000],
  ['Launch event recording.mp4', 'Videos', 612_000_000],
  ['Asset pack.zip', 'Archives', 42_000_000],
]

function demoCategoryMeta(profile: Profile, index: number): Record<string, unknown> {
  const rules = (profile.parameters.typeRules ?? []).filter((rule) => rule.enabled)
  if (profile.presetType !== 'by-type' || !rules.length) return {}
  const rule = rules[index % rules.length]
  const ai = (rule.kind ?? 'extension') === 'content'
  return { category: rule.id, categoryName: rule.name, confidence: ai ? (['high', 'medium', 'low'] as const)[index % 3] : 'high', source: ai ? 'analysis' : rule.kind ?? 'extension' }
}

class DemoApi {
  private handlers = new Set<EventHandler>()
  private plan?: Plan
  private history: any[] = []
  private quarantine: any[] = []
  private profiles: Profile[] = []
  private settings = { theme: 'system', retentionDays: 30, historyLimit: 200, redactPaths: true, notifyOnComplete: true, onboardingCompleted: false, defaultTargetFolder: '~/Documents/Organize', quarantineFolder: 'App data/quarantine',
    aiEnabled: true, aiEmbedModel: 'nomic-embed-text', aiLlmModel: 'qwen2.5:3b-instruct', aiDescriptions: false, aiThreshold: 0.75, aiOcr: false }
  private proposal?: Proposal

  private demoCategory(id: string, kind: ProposalCategory['kind'], name: string, names: string[], high: number, medium = 0, low = 0): ProposalCategory {
    return { id, kind, name, folderName: name, description: null, count: high + medium + low, examples: names.map((item, index) => ({ index: Number(id.slice(1)) * 100 + index, name: item })),
      confidence: { high, medium, low }, splittable: kind === 'content' && high + medium + low >= 8 }
  }

  onEvent(handler: EventHandler) {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  private emit(event: string, payload: Record<string, unknown>) {
    this.handlers.forEach((handler) => handler({ event, payload }))
  }

  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (method === 'app.initialize') {
      return { engineVersion: '0.1.0-demo', firstLaunch: !this.settings.onboardingCompleted, dataDir: 'App data/organize-gui', recoverableRuns: this.history.length, quarantineCount: this.quarantine.length } as T
    }
    if (method === 'app.version') return { engine: '0.2.0-demo', organize: '3.3.0' } as T
    if (method === 'preset.list') {
      return [
        { id: 'by-type', name: 'Organize files by type', description: 'Choose folders and category rules; documents, images and more each go to one place.', operation: 'move' },
        { id: 'by-date', name: 'Archive images by date', description: 'Organizes photos and screenshots by year and month of the date taken.', operation: 'move' },
        { id: 'old-installers', name: 'Clean up old installers', description: 'Free up space taken by old installers.', operation: 'quarantine' },
        { id: 'duplicates', name: 'Duplicate file finder', description: 'Only byte-for-byte identical content counts as a duplicate.', operation: 'quarantine' },
      ] as T
    }
    if (method === 'profile.validate') return { valid: true, issues: [] } as T
    if (method === 'profile.list') return this.profiles as T
    if (method === 'profile.save') {
      const profile = JSON.parse(JSON.stringify(params.profile)) as Profile
      this.profiles = [profile, ...this.profiles.filter((item) => item.id !== profile.id)]
      return profile as T
    }
    if (method === 'profile.delete') { this.profiles = this.profiles.filter((item) => item.id !== params.profileId); return { deleted: true } as T }
    if (method === 'plan.create') {
      const profile = params.profile as Profile
      for (let checked = 320; checked <= 1920; checked += 320) {
        await new Promise((resolve) => setTimeout(resolve, 90))
        this.emit('plan.progress', { checked, path: `${profile.sourceFolders[0]}/Sample file-${checked}.pdf` })
      }
      const items: PlanItem[] = sampleFiles.map(([name, folder, size], index) => ({
          itemId: `demo-${index}`,
          sequence: index,
          operation: profile.presetType === 'old-installers' || profile.presetType === 'duplicates' ? 'quarantine' : 'move',
          sourcePath: `${profile.sourceFolders[0]}/${name}`,
          targetPath: `${profile.targetFolder}/${folder}/${index === 2 ? 'Quotation 2.pdf' : name}`,
          size: Number(size),
          selected: profile.presetType !== 'duplicates',
          status: 'planned',
          warningCode: index === 2 ? 'TARGET_CONFLICT' : null,
          reason: null,
          groupId: profile.presetType === 'duplicates' ? `group-${Math.floor(index / 2)}` : null,
          metadata: profile.presetType === 'duplicates' ? { recommendedKeep: index % 2 === 0, decision: 'undecided' } : demoCategoryMeta(profile, index),
        }))
      if (profile.presetType === 'by-type') items.forEach((item) => {
        if (item.metadata.source === 'analysis' && item.metadata.confidence !== 'high') item.selected = false
        const rule = (profile.parameters.typeRules ?? []).find((candidate) => candidate.id === item.metadata.category)
        if (rule) item.targetPath = `${profile.targetFolder}/${rule.folderName}/${item.sourcePath.split('/').at(-1)}`
      })
      this.plan = {
        planId: crypto.randomUUID(), status: 'ready', createdAt: new Date().toISOString(),
        expiresAt: new Date(Date.now() + 30 * 60_000).toISOString(), profile,
        summary: {
          total: items.length, selected: items.filter((x) => x.selected).length,
          selectedBytes: items.filter((x) => x.selected).reduce((n, x) => n + x.size, 0),
          move: items.filter((x) => x.selected && x.operation === 'move').length,
          quarantine: items.filter((x) => x.selected && x.operation === 'quarantine').length,
          skip: 0, conflict: 1, groups: profile.presetType === 'duplicates' ? 4 : 0,
        }, items,
      }
      this.emit('plan.completed', { planId: this.plan.planId, summary: this.plan.summary })
      return this.plan as T
    }
    if (method === 'plan.excludeItems') {
      const selected = new Set(params.selectedItemIds as string[])
      this.plan!.items.forEach((item) => { item.selected = selected.has(item.itemId) })
      this.plan!.summary.selected = selected.size
      this.plan!.summary.selectedBytes = this.plan!.items.filter((x) => x.selected).reduce((n, x) => n + x.size, 0)
      return this.plan as T
    }
    if (method === 'run.execute') {
      const selected = this.plan!.items.filter((item) => item.selected)
      for (let index = 0; index < selected.length; index++) {
        await new Promise((resolve) => setTimeout(resolve, 180))
        this.emit('run.item', { status: 'applied', index: index + 1, total: selected.length, item: selected[index] })
      }
      const result: RunResult = {
        runId: crypto.randomUUID(), planId: this.plan!.planId, status: 'completed',
        total: selected.length, success: selected.length, skipped: 0, failed: 0,
        successBytes: selected.reduce((sum, item) => sum + item.size, 0),
        endedAt: new Date().toISOString(),
      }
      this.history.unshift({ ...result, undoable_count: selected.length, run_id: result.runId, plan_id: result.planId, profile: this.plan!.profile, started_at: new Date().toISOString() })
      if (this.plan!.profile.presetType === 'old-installers' || this.plan!.profile.presetType === 'duplicates') {
        this.quarantine.unshift(...selected.map((item) => ({
          quarantine_id: `q-${item.itemId}`, operation_id: item.itemId,
          original_path: item.sourcePath, quarantine_path: item.targetPath,
          reason: item.reason ?? 'Moved to quarantine per the plan', size: item.size,
          quarantined_at: new Date().toISOString(), retention_until: new Date(Date.now() + 30 * 86400_000).toISOString(), status: 'active',
        })))
      }
      this.emit('run.completed', { result })
      return result as T
    }
    if (method === 'classifier.status') {
      return { aiEnabled: this.settings.aiEnabled, ollamaInstalled: true, vectorBackend: 'accelerate', maxCategories: 12,
        models: params.probe ? ['nomic-embed-text:latest', 'qwen2.5:3b-instruct'] : null,
        embedModelInstalled: params.probe ? true : null, llmModelInstalled: params.probe ? true : null, error: null } as T
    }
    if (method === 'analysis.scan') {
      for (let done = 1; done <= 120; done += 40) { await new Promise((resolve) => setTimeout(resolve, 60)); this.emit('analysis.progress', { stage: 'reading', done }) }
      return { analysisId: 'demo-analysis', summary: { files: 128, bytes: 734_000_000, families: { documents: 61, images: 38, videos: 6, audio: 4, archives: 7, installers: 5, other: 7 },
        topExtensions: [{ extension: 'pdf', count: 34 }, { extension: 'jpg', count: 22 }, { extension: 'png', count: 16 }, { extension: 'docx', count: 14 }], photos: 22, screenshots: 12, withDateTaken: 22, withLocation: 9 } } as T
    }
    if (method === 'analysis.discover') {
      const ai = params.options && (params.options as { mode?: string }).mode === 'ai' && this.settings.aiEnabled
      for (const stage of ai ? ['reading', 'embedding', 'grouping', 'naming'] : ['reading']) {
        for (let done = 1; done <= 4; done++) { await new Promise((resolve) => setTimeout(resolve, 120)); this.emit('analysis.progress', { stage, done, total: 4 }) }
      }
      const categories = [
        this.demoCategory('c1', 'metadata', 'Spain Jun 2025', ['IMG_2041.HEIC', 'IMG_2042.HEIC', 'IMG_2050.JPG'], 9),
        this.demoCategory('c2', 'metadata', 'Screenshots', ['Screenshot 2026-02-10 at 09.12.44.png', 'CleanShot 2026-03-01.png'], 12),
        this.demoCategory('c3', 'metadata', 'Camera photos', ['IMG_1001.JPG', 'IMG_1002.JPG'], 13),
        ...(ai ? [
          this.demoCategory('c4', 'content', 'Invoices', ['Invoice 4821 Acme.pdf', 'Fattura 2201.pdf', 'Hosting bill March.pdf'], 18, 4, 1),
          this.demoCategory('c5', 'content', 'Travel bookings', ['Boarding pass Madrid.pdf', 'Hotel booking Lisbon.pdf'], 7, 2),
          this.demoCategory('c6', 'content', 'Recipes', ['Risotto recipe.md', 'Grandma Lasagna.docx'], 6, 1),
          this.demoCategory('c7', 'content', 'Meeting notes', ['Weekly sync May.md', 'Project kickoff notes.docx'], 9, 3, 2),
        ] : [this.demoCategory('c4', 'extension', 'Documents', ['Invoice 4821 Acme.pdf', 'Risotto recipe.md'], 52)]),
        this.demoCategory('c8', 'extension', 'Installers', ['Editor-installer-2.1.dmg', 'Notes setup.pkg'], 5),
      ]
      this.proposal = { analysisId: 'demo-analysis', mode: ai ? 'ai' : 'heuristic', notice: ai ? null : this.settings.aiEnabled ? 'AI_UNAVAILABLE' : 'AI_DISABLED', tooFew: false, total: 128,
        categories, other: { count: 14, examples: [{ index: 9001, name: 'random.bin' }, { index: 9002, name: 'notes.xyz' }] }, maxCategories: 12 }
      return this.proposal as T
    }
    if (method === 'analysis.split') {
      const source = this.proposal?.categories.find((item) => item.id === params.categoryId)
      if (!source) throw new Error('Only AI content categories can be split.')
      const half = Math.floor(source.count / 2)
      const created = [this.demoCategory('c91', 'content', `${source.name} A`, source.examples.slice(0, 2).map((item) => item.name), half),
        this.demoCategory('c92', 'content', `${source.name} B`, source.examples.slice(2).map((item) => item.name), source.count - half)]
      return { ...this.proposal!, categories: [...this.proposal!.categories.filter((item) => item.id !== source.id), ...created], created: created.map((item) => item.id), replaced: source.id } as T
    }
    if (method === 'analysis.accept') {
      const profile = JSON.parse(JSON.stringify(params.profile)) as Profile
      const kinds = Object.fromEntries((this.proposal?.categories ?? []).map((item) => [item.id, item.kind]))
      profile.parameters.typeRules = (params.categories as Array<{ id: string; name: string; folderName: string; sources: string[] }>).map((item): TypeRule => {
        const kind = kinds[item.sources[0]] ?? 'content'
        return { id: crypto.randomUUID(), name: item.name, folderName: item.folderName, enabled: true, kind,
          extensions: kind === 'content' ? [] : kind === 'metadata' ? ['jpg', 'jpeg', 'heic', 'png'] : ['dmg', 'pkg'],
          ...(kind === 'metadata' ? { match: { hasCamera: true } } : kind === 'content' ? { centroidRef: crypto.randomUUID() } : {}) }
      })
      profile.parameters.unmatchedAction = 'other'
      profile.parameters.otherFolder ??= 'Other files'
      return { profile, analysisId: 'demo-analysis' } as T
    }
    if (method === 'analysis.cancel') return { accepted: true } as T
    if (method === 'ai.clearData') return { cleared: { content_cache: 0, category_models: 0, analysis_assignments: 0 } } as T
    if (method === 'plan.setItemCategory' || method === 'plan.acceptSuggestions') {
      const rules = this.plan!.profile.parameters.typeRules ?? []
      for (const item of this.plan!.items) {
        const levels = params.minConfidence === 'medium' ? ['high', 'medium'] : params.minConfidence === 'low' ? ['high', 'medium', 'low'] : ['high']
        if (method === 'plan.acceptSuggestions' && levels.includes(String(item.metadata.confidence))) item.selected = true
        if (method === 'plan.setItemCategory' && item.itemId === params.itemId) {
          const rule = rules.find((candidate) => candidate.id === params.categoryId)
          const folder = rule?.folderName ?? this.plan!.profile.parameters.otherFolder ?? 'Other files'
          item.targetPath = `${this.plan!.profile.targetFolder}/${folder}/${item.sourcePath.split('/').at(-1)}`
          item.metadata = { ...item.metadata, category: params.categoryId, categoryName: rule?.name ?? folder, confidence: 'high', source: 'manual' }
          item.selected = true
        }
      }
      this.plan!.summary.selected = this.plan!.items.filter((x) => x.selected).length
      return this.plan as T
    }
    if (method === 'run.cancel' || method === 'plan.cancel') return { accepted: true } as T
    if (method === 'history.list') return this.history as T
    if (method === 'history.detail') {
      const run = this.history.find((item) => item.run_id === params.runId)
      return { ...run, operations: (this.plan?.items ?? []).filter((item) => item.selected).map((item) => ({
        operation_id: item.itemId, operation: item.operation, source_path: item.sourcePath,
        target_path: item.targetPath, state: 'applied', error_code: null, error_detail: null,
      })) } as T
    }
    if (method === 'history.undoPlan') {
      return { runId: params.runId, items: (this.plan?.items ?? []).filter((item) => item.selected).map((item) => ({ operationId: item.itemId, currentPath: item.targetPath, restorePath: item.sourcePath, size: item.size, state: 'ready', selected: true })) } as T
    }
    if (method === 'history.undo') return { runId: params.runId, restored: (params.operationIds as string[]).length, failed: 0 } as T
    if (method === 'quarantine.list') return this.quarantine as T
    if (method === 'quarantine.restore' || method === 'quarantine.moveToTrash') {
      const ids = new Set(params.quarantineIds as string[])
      this.quarantine = this.quarantine.filter((item) => !ids.has(item.quarantine_id))
      return { requested: ids.size, restored: ids.size, moved: ids.size, failed: 0 } as T
    }
    if (method === 'settings.get') return this.settings as T
    if (method === 'settings.update') {
      this.settings = { ...this.settings, ...(params.values as typeof this.settings) }
      return this.settings as T
    }
    if (method === 'diagnostics.export') return { path: params.destination, size: 2048 } as T
    throw new Error(`Demo API Not implemented: ${method}`)
  }
}

class TauriApi {
  private handlers = new Set<EventHandler>()
  private listening = false

  onEvent(handler: EventHandler) {
    this.handlers.add(handler)
    void this.ensureListener()
    return () => this.handlers.delete(handler)
  }

  private async ensureListener() {
    if (this.listening) return
    this.listening = true
    const { listen } = await import('@tauri-apps/api/event')
    await listen<EngineEvent>('engine-event', ({ payload }) => {
      this.handlers.forEach((handler) => handler(payload))
    })
  }

  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const { invoke } = await import('@tauri-apps/api/core')
    try {
      const raw = await invoke<any>('engine_request', { method, params })
      if (['plan.create', 'plan.get', 'plan.excludeItems', 'plan.setItemCategory', 'plan.acceptSuggestions'].includes(method)) return camelPlan(raw) as T
      return raw as T
    } catch (caught) {
      if (caught && typeof caught === 'object') {
        const value = caught as Record<string, unknown>
        throw new Error(`${String(value.message ?? 'Organizing engine request failed')} (${String(value.code ?? 'UNKNOWN')})`)
      }
      throw caught
    }
  }
}

export interface AppApi {
  request<T>(method: string, params?: Record<string, unknown>): Promise<T>
  onEvent(handler: EventHandler): () => void
}

const isTauri = '__TAURI_INTERNALS__' in window
export const api: AppApi = isTauri ? new TauriApi() : new DemoApi()

export async function pickDirectories(multiple = false): Promise<string[]> {
  if (isTauri) {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result = await open({ directory: true, multiple })
    if (!result) return []
    return Array.isArray(result) ? result : [result]
  }
  const value = window.prompt(multiple ? 'Enter folder path (separate multiple paths with commas)' : 'Enter folder path')
  return value ? value.split(',').map((item) => item.trim()).filter(Boolean) : []
}

export async function pickDiagnosticPath(): Promise<string | undefined> {
  if (isTauri) {
    const { save } = await import('@tauri-apps/plugin-dialog')
    return await save({
      defaultPath: `organize-diagnostics-${new Date().toISOString().slice(0, 10)}.zip`,
      filters: [{ name: 'ZIP Archives', extensions: ['zip'] }],
    }) ?? undefined
  }
  return '/tmp/organize-diagnostics.zip'
}

export async function revealLocalPath(path: string): Promise<void> {
  if (!isTauri) return
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('reveal_path', { path })
}

export async function notifyCompletion(result: RunResult): Promise<void> {
  if (!isTauri) return
  const { isPermissionGranted, sendNotification } = await import('@tauri-apps/plugin-notification')
  if (!await isPermissionGranted()) throw new Error('System notifications not authorized')
  sendNotification({ title: 'Organize · Organizing finished', body: `${result.success} completed, ${result.skipped} skipped, ${result.failed} failed.` })
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (!isTauri) return true
  const { isPermissionGranted, requestPermission } = await import('@tauri-apps/plugin-notification')
  return await isPermissionGranted() || await requestPermission() === 'granted'
}

export async function openLegalResource(resource: 'licenses' | 'mpl-sources'): Promise<boolean> {
  if (!isTauri) return false
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('open_legal_resource', { resource })
  return true
}
