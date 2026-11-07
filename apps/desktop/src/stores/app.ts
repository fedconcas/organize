import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, notifyCompletion } from '../api'
import { ensureClassification } from '../profiles'
import type { HistoryDetail, HistoryRun, Plan, Preset, PresetType, Profile, QuarantineItem, RunResult, Settings, UndoPreview, ViewName } from '../types'

const categories = ['documents', 'images', 'videos', 'audio', 'archives', 'installers', 'other']

function makeProfile(preset: PresetType): Profile {
  const names: Record<PresetType, string> = {
    'by-type': 'Organize files by type',
    'by-date': 'Archive images by date',
    'old-installers': 'Clean up old installers',
    duplicates: 'Duplicate file finder',
    'similar-photos': 'Similar photos',
  }
  return {
    id: crypto.randomUUID(), name: names[preset], presetType: preset,
    sourceFolders: ['~/Downloads'], targetFolder: '~/Documents/Organize',
    includeSubfolders: preset === 'duplicates' || preset === 'similar-photos', schemaVersion: 1,
    parameters: {
      categories: [...categories], olderThanDays: 90,
      includeArchives: false, minimumBytes: preset === 'similar-photos' ? 0 : 1024 * 1024,
      scanExact: true, scanSimilar: true, maxDifference: 5, hashSize: 16,
      geometricInvariance: true, keepRule: 'resolution',
    },
  }
}

export const useAppStore = defineStore('app', () => {
  const view = ref<ViewName>('home')
  const presets = ref<Preset[]>([])
  const profile = ref<Profile>(makeProfile('by-type'))
  const plan = ref<Plan>()
  const result = ref<RunResult>()
  const undoPreview = ref<UndoPreview>()
  const history = ref<HistoryRun[]>([])
  const historyDetail = ref<HistoryDetail>()
  const quarantine = ref<QuarantineItem[]>([])
  const engineReady = ref(false)
  const startupState = ref<'loading' | 'ready' | 'error'>('loading')
  const startupError = ref<string>()
  const error = ref<string>()
  const scanChecked = ref(0)
  const scanPath = ref('')
  const scanLabel = ref('')
  const runCompleted = ref(0)
  const runCurrent = ref('')
  const busy = ref(false)
  const theme = ref<'system' | 'light' | 'dark'>('system')
  const settings = ref<Settings>({ theme: 'system', retentionDays: 30, historyLimit: 200, redactPaths: true,
    notifyOnComplete: true, defaultTargetFolder: '~/Documents/Organize', quarantineFolder: '' })
  const savedProfiles = ref<Profile[]>([])
  const lastProfile = ref<Profile>()
  const notice = ref('')
  const runSuccess = ref(0)
  const runSkipped = ref(0)
  const runFailed = ref(0)
  let scanCancelled = false
  let detailRequest = 0
  let startupInFlight = false
  let unsubscribeEvents: (() => void) | undefined

  function report(caught: unknown) { error.value = caught instanceof Error ? caught.message : String(caught) }

  function useProfile(value: Profile) {
    profile.value = JSON.parse(JSON.stringify(value))
    ensureClassification(profile.value)
    view.value = 'config'
  }
  async function saveProfile() {
    try {
      await api.request('profile.save', { profile: profile.value })
      savedProfiles.value = await api.request<Profile[]>('profile.list')
      notice.value = 'Plan saved. You can select it again in plan settings.'
    } catch (caught) { report(caught) }
  }
  async function deleteProfile(id: string) {
    try {
      await api.request('profile.delete', { profileId: id })
      savedProfiles.value = await api.request<Profile[]>('profile.list')
    } catch (caught) { report(caught) }
  }
  async function updateSettings(values: Partial<Settings>) {
    try {
      settings.value = await api.request<Settings>('settings.update', { values })
      theme.value = settings.value.theme
      await refreshCollections()
      return true
    } catch (caught) { report(caught); return false }
  }

  const selectedItems = computed(() => plan.value?.items.filter((item) => item.selected) ?? [])
  const selectedBytes = computed(() => selectedItems.value.reduce((sum, item) => sum + item.size, 0))

  function go(next: ViewName) {
    view.value = next
  }

  function choosePreset(id: PresetType) {
    profile.value = makeProfile(id)
    profile.value.targetFolder = settings.value.defaultTargetFolder
    ensureClassification(profile.value)
    view.value = 'config'
  }

  async function initialize() {
    if (startupInFlight || startupState.value === 'ready') return
    startupInFlight = true
    startupState.value = 'loading'
    startupError.value = undefined
    error.value = undefined
    engineReady.value = false
    try {
      unsubscribeEvents ??= api.onEvent(({ event, payload }) => {
        if (event === 'plan.progress') {
          scanChecked.value = Number(payload.checked ?? payload.hashed ?? scanChecked.value)
          scanPath.value = String(payload.path ?? scanPath.value)
          scanLabel.value = String(payload.label ?? scanLabel.value)
        }
        if (event === 'run.item') {
          runCompleted.value = Number(payload.index ?? runCompleted.value)
          runSuccess.value = Number(payload.success ?? (payload.status === 'applied' ? runSuccess.value + 1 : runSuccess.value))
          runSkipped.value = Number(payload.skipped ?? runSkipped.value)
          runFailed.value = Number(payload.failed ?? runFailed.value)
          const item = payload.item as Record<string, unknown> | undefined
          runCurrent.value = String(item?.sourcePath ?? item?.source_path ?? '')
        }
      })
      const [initial, loadedPresets, loadedSettings, profiles] = await Promise.all([
        api.request<{ firstLaunch: boolean; lastProfile?: Profile }>('app.initialize'),
        api.request<Preset[]>('preset.list'),
        api.request<Settings>('settings.get'), api.request<Profile[]>('profile.list'),
      ])
      presets.value = loadedPresets
      settings.value = loadedSettings
      theme.value = loadedSettings.theme
      savedProfiles.value = profiles
      lastProfile.value = initial.lastProfile
      if (initial.lastProfile) {
        profile.value = JSON.parse(JSON.stringify(initial.lastProfile))
        ensureClassification(profile.value)
      } else profile.value.targetFolder = loadedSettings.defaultTargetFolder
      await refreshCollections()
      if (initial.firstLaunch && !history.value.length) view.value = 'onboarding'
      engineReady.value = true
      startupState.value = 'ready'
    } catch (caught) {
      startupError.value = caught instanceof Error ? caught.message : String(caught)
      startupState.value = 'error'
    } finally {
      startupInFlight = false
    }
  }

  async function validateProfile() {
    return api.request<{ valid: boolean; issues: Array<Record<string, unknown>> }>('profile.validate', { profile: profile.value })
  }

  async function createPlan() {
    busy.value = true
    error.value = undefined
    scanChecked.value = 0
    scanLabel.value = ''
    scanCancelled = false
    scanPath.value = profile.value.sourceFolders[0] ?? ''
    view.value = 'scan'
    try {
      plan.value = await api.request<Plan>('plan.create', { profile: profile.value })
      if (scanCancelled) return
      lastProfile.value = JSON.parse(JSON.stringify(profile.value))
      view.value = profile.value.presetType === 'duplicates' || profile.value.presetType === 'similar-photos' ? 'duplicates' : 'preview'
    } catch (caught) {
      if (!scanCancelled) report(caught)
      view.value = 'config'
    } finally {
      busy.value = false
    }
  }

  async function persistSelection() {
    if (!plan.value) return
    plan.value = await api.request<Plan>('plan.excludeItems', {
      planId: plan.value.planId,
      selectedItemIds: selectedItems.value.map((item) => item.itemId),
    })
  }

  function toggleItem(itemId: string) {
    const item = plan.value?.items.find((candidate) => candidate.itemId === itemId)
    if (!item || item.status === 'skipped') return
    item.selected = !item.selected
  }

  function selectDuplicateKeep(groupId: string, keepId: string) {
    plan.value?.items.filter((item) => item.groupId === groupId).forEach((item) => {
      item.selected = item.itemId !== keepId
      item.metadata.decision = item.itemId === keepId ? 'keep' : 'quarantine'
    })
  }

  async function executePlan() {
    if (!plan.value) return
    busy.value = true
    runCompleted.value = 0
    runSuccess.value = runSkipped.value = runFailed.value = 0
    runCurrent.value = ''
    view.value = 'executing'
    try {
      await persistSelection()
      result.value = await api.request<RunResult>('run.execute', { planId: plan.value.planId })
      view.value = 'result'
      await refreshCollections()
      if (settings.value.notifyOnComplete && document.hidden) {
        try { await notifyCompletion(result.value) } catch { notice.value = 'Organizing is finished, but the system notification could not be sent. Please check notification permissions.' }
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
      view.value = profile.value.presetType === 'duplicates' || profile.value.presetType === 'similar-photos' ? 'duplicates' : 'preview'
    } finally {
      busy.value = false
    }
  }

  async function cancelRun() {
    await api.request('run.cancel')
  }

  async function cancelScan() {
    scanCancelled = true
    await api.request('plan.cancel')
    view.value = 'config'
  }

  async function refreshCollections() {
    try {
      const [runs, items] = await Promise.all([
        api.request<HistoryRun[]>('history.list'),
        api.request<QuarantineItem[]>('quarantine.list'),
      ])
      history.value = runs
      quarantine.value = items
    } catch (caught) { report(caught) }
  }

  async function completeOnboarding() {
    await api.request('settings.update', { values: { onboardingCompleted: true } })
    view.value = 'home'
  }

  async function prepareUndo(runId: string) {
    busy.value = true
    error.value = undefined
    try {
      undoPreview.value = await api.request<UndoPreview>('history.undoPlan', { runId })
      view.value = 'undo'
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      busy.value = false
    }
  }

  async function loadHistoryDetail(runId: string) {
    const request = ++detailRequest
    historyDetail.value = undefined
    try {
      const detail = await api.request<HistoryDetail>('history.detail', { runId })
      if (request === detailRequest) historyDetail.value = detail
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    }
  }

  async function executeUndo(operationIds: string[]) {
    if (!undoPreview.value) return
    busy.value = true
    error.value = undefined
    try {
      await api.request('history.undo', { runId: undoPreview.value.runId, operationIds })
      await refreshCollections()
      view.value = 'history'
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : String(caught)
    } finally {
      busy.value = false
    }
  }

  async function restoreQuarantine(quarantineIds: string[], destinationFolder?: string) {
    return quarantineAction('quarantine.restore', quarantineIds, destinationFolder)
  }

  async function trashQuarantine(quarantineIds: string[]) {
    return quarantineAction('quarantine.moveToTrash', quarantineIds)
  }
  async function quarantineAction(method: string, quarantineIds: string[], destinationFolder?: string) {
    busy.value = true
    try {
      const counts = await api.request<{ restored?: number; moved?: number; skipped?: number; failed: number }>(method, { quarantineIds, destinationFolder })
      notice.value = `Processed ${counts.restored ?? counts.moved ?? 0} items, skipped ${counts.skipped ?? 0} items, failed ${counts.failed} items.`
      await refreshCollections()
      return true
    } catch (caught) { report(caught); return false } finally { busy.value = false }
  }

  return {
    view, presets, profile, plan, result, undoPreview, history, historyDetail, quarantine, engineReady, startupState, startupError, error,
    scanChecked, scanPath, scanLabel, runCompleted, runCurrent, busy, theme, settings, savedProfiles, lastProfile, notice, runSuccess, runSkipped, runFailed,
    useProfile, saveProfile, deleteProfile, updateSettings, report,
    selectedItems, selectedBytes,
    go, choosePreset, initialize, validateProfile, createPlan, toggleItem,
    selectDuplicateKeep, persistSelection, executePlan, cancelRun, cancelScan,
    refreshCollections, completeOnboarding, prepareUndo, loadHistoryDetail, executeUndo,
    restoreQuarantine, trashQuarantine,
  }
})
