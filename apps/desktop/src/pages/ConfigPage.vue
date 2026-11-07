<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { pickDirectories } from '../api'
import { ruleIssues, stableStringify, type RuleIssue } from '../profiles'
import AppIcon from '../components/AppIcon.vue'
import ProfileMenu from '../components/ProfileMenu.vue'
import SwitchToggle from '../components/SwitchToggle.vue'
import TypeRulesEditor from '../components/TypeRulesEditor.vue'

const store = useAppStore()
const validating = ref(false)
const serverIssues = ref<Array<Record<string, unknown>>>([])
const expandedRule = ref<string>()

const PRESETS = {
  'by-type': { label: 'Sort by type', icon: 'folder', description: 'Puts files into matching subfolders by extension.' },
  'by-date': { label: 'Archive by date', icon: 'image', description: 'Puts files by modified date into “Year/Month” folders.' },
  'old-installers': { label: 'Clean up old installers', icon: 'download', description: 'Move long-unused installers to quarantine; restore any time.' },
  duplicates: { label: 'Duplicate file finder', icon: 'duplicate', description: 'Finds files with identical content; you decide which copy to keep.' },
  'similar-photos': { label: 'Similar photos', icon: 'image', description: 'Finds identical and similar-looking photos. Rotated and flipped copies are found too.' },
} as const
const preset = computed(() => PRESETS[store.profile.presetType])
const params = computed(() => store.profile.parameters)
const isByType = computed(() => store.profile.presetType === 'by-type')
const fixedTarget = computed(() => ['old-installers', 'duplicates', 'similar-photos'].includes(store.profile.presetType))
const photos = computed(() => store.profile.presetType === 'similar-photos')
const scanModeMissing = computed(() => photos.value && params.value.scanExact === false && params.value.scanSimilar === false)
const baseName = (path: string) => path.replace(/\/+$/, '').split('/').at(-1) || path
const targetPath = computed(() => fixedTarget.value ? store.settings.quarantineFolder || 'App quarantine' : store.profile.targetFolder)
const targetName = computed(() => fixedTarget.value ? 'Quarantine' : baseName(store.profile.targetFolder))

const savedEntry = computed(() => store.savedProfiles.find((profile) => profile.id === store.profile.id))
const saveState = computed(() => !savedEntry.value ? 'new' : stableStringify(savedEntry.value) === stableStringify(store.profile) ? 'saved' : 'dirty')
const SAVE_LABELS = { new: 'Unsaved', saved: 'Saved', dirty: 'Unsaved changes' }

const SERVER_LABELS: Record<string, string> = {
  SOURCE_NOT_FOUND: 'Source folder does not exist', SOURCE_NOT_READABLE: 'Source folder cannot be read', TARGET_NOT_WRITABLE: 'The target folder cannot be written to',
  SOURCE_TARGET_OVERLAP: 'The target folder cannot be placed inside the source', QUARANTINE_OVERLAP: 'Source folder cannot overlap the quarantine',
  INVALID_RULE_NAME: 'Category name cannot be empty', INVALID_RULE_FOLDER: 'Subfolder name is invalid', INVALID_RULE_EXTENSIONS: 'Invalid extension',
  DUPLICATE_EXTENSION: 'Extension belongs to multiple categories', NO_CATEGORIES: 'Enable at least one category, or put unmatched files into the Other folder',
  INVALID_TYPE_RULES: 'Category rules are malformed', INVALID_UNMATCHED_ACTION: 'How to handle unmatched files is invalid',
}
const RULE_FIELDS: Record<string, RuleIssue['field']> = {
  INVALID_RULE_NAME: 'name', INVALID_RULE_FOLDER: 'folder', INVALID_RULE_EXTENSIONS: 'extensions', DUPLICATE_EXTENSION: 'extensions',
}
const serverLabel = (issue: Record<string, unknown>) => {
  const label = SERVER_LABELS[String(issue.code)] ?? String(issue.code)
  const detail = issue.extension ? `“${issue.extension}”` : issue.path ? `: ${issue.path}` : ''
  return `${label}${detail}`
}

const issues = computed<RuleIssue[]>(() => {
  if (!isByType.value) return []
  const local = ruleIssues(store.profile)
  const rules = params.value.typeRules ?? []
  for (const issue of serverIssues.value) {
    const field = String(issue.field ?? '')
    const index = /^parameters\.typeRules\.(\d+)/.exec(field)?.[1]
    const ruleId = index === undefined ? undefined : rules[Number(index)]?.id
    const mapped: RuleIssue['field'] | undefined = RULE_FIELDS[String(issue.code)] ?? (field === 'parameters.otherFolder' ? 'other' : undefined)
    if (mapped && !local.some((item) => item.ruleId === ruleId && item.field === mapped)) local.push({ ruleId, field: mapped, message: serverLabel(issue) })
  }
  return local
})
const environmentIssues = computed(() => serverIssues.value.filter((issue) => !String(issue.code).startsWith('INVALID_RULE') && !['DUPLICATE_EXTENSION', 'NO_CATEGORIES', 'INVALID_TYPE_RULES', 'INVALID_UNMATCHED_ACTION'].includes(String(issue.code)) && issue.field !== 'parameters.otherFolder'))

const normalized = (path: string) => path.replace(/\/+$/, '')
const targetInsideSource = computed(() => !fixedTarget.value && store.profile.sourceFolders.some((source) => {
  const target = normalized(store.profile.targetFolder)
  return target === normalized(source) || target.startsWith(`${normalized(source)}/`)
}))
const blockers = computed(() => (store.profile.sourceFolders.length ? 0 : 1) + (targetInsideSource.value ? 1 : 0) + issues.value.length + (scanModeMissing.value ? 1 : 0))

const enabledRules = computed(() => (params.value.typeRules ?? []).map((rule, index) => ({ rule, index })).filter(({ rule }) => rule.enabled))
const now = new Date()
const summary = computed(() => {
  const sources = `${store.profile.sourceFolders.length} sources`
  if (isByType.value) return `${sources} → ${enabledRules.value.length} categories${params.value.unmatchedAction === 'keep' ? ', unmatched files stay in place' : ''}`
  if (store.profile.presetType === 'by-date') return `${sources} → Archive by “Year/Month”`
  if (store.profile.presetType === 'old-installers') return `${sources} → Installers older than ${params.value.olderThanDays ?? 90} days are moved to quarantine`
  if (photos.value) return `${sources} → Exact duplicates ${params.value.scanExact === false ? 'off' : 'on'}, similar ${params.value.scanSimilar === false ? 'off' : 'on'}`
  return `${sources} → Find duplicate files and confirm group by group`
})

async function addSource() {
  for (const value of await pickDirectories(true)) {
    if (!store.profile.sourceFolders.includes(value)) store.profile.sourceFolders.push(value)
  }
}
async function replaceSource(index: number) {
  const [value] = await pickDirectories(false)
  if (value && !store.profile.sourceFolders.some((source, i) => source === value && i !== index)) store.profile.sourceFolders[index] = value
}
async function changeTarget() {
  const [value] = await pickDirectories(false)
  if (value) store.profile.targetFolder = value
}
async function focusRule(ruleId?: string) {
  if (!ruleId) return
  expandedRule.value = ruleId
  await nextTick()
  document.querySelector(`[data-rule="${ruleId}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}
async function scan() {
  validating.value = true
  try {
    const result = await store.validateProfile()
    serverIssues.value = result.issues
    if (result.valid) await store.createPlan()
  } catch (caught) { store.report(caught) } finally { validating.value = false }
}
</script>

<template>
  <div class="page flow-page config-page">
    <header class="config-header">
      <div class="config-title">
        <span class="config-kicker"><AppIcon :name="preset.icon" :size="14" />{{ preset.label }}</span>
        <label class="title-field" title="Click to rename plan">
          <input v-model="store.profile.name" maxlength="80" aria-label="Plan name" placeholder="Give this plan a name" />
          <AppIcon name="edit" :size="15" />
        </label>
        <p>{{ preset.description }}</p>
      </div>
      <div class="config-tools">
        <span class="save-state" :class="saveState"><i />{{ SAVE_LABELS[saveState] }}</span>
        <ProfileMenu :saved="Boolean(savedEntry)" @loaded="serverIssues = []; expandedRule = undefined" />
        <button class="button secondary" :disabled="saveState === 'saved' || !store.profile.name.trim()" @click="store.saveProfile">Save plan</button>
      </div>
    </header>

    <div class="config-grid">
      <div class="config-main">
        <section class="panel config-section route-panel">
          <header class="section-head">
            <div class="section-title"><h2>Scope</h2><p>Scanning only reads file info and changes no files</p></div>
            <div class="section-actions"><button class="button secondary small" @click="addSource"><AppIcon name="plus" :size="15" />Add source</button></div>
          </header>
          <div class="route">
            <div class="route-label">Source</div>
            <div v-for="(source, index) in store.profile.sourceFolders" :key="`${source}-${index}`" class="path-row">
              <span class="path-icon"><AppIcon name="folder" :size="17" /></span>
              <span class="path-text"><b>{{ baseName(source) }}</b><code :title="source">{{ source }}</code></span>
              <span class="path-actions">
                <button class="icon-button" title="Change folder" :aria-label="`Change source ${baseName(source)}`" @click="replaceSource(index)"><AppIcon name="swap" :size="15" /></button>
                <button class="icon-button danger" title="Remove" :aria-label="`Remove source ${baseName(source)}`" @click="store.profile.sourceFolders.splice(index, 1)"><AppIcon name="close" :size="15" /></button>
              </span>
            </div>
            <button v-if="!store.profile.sourceFolders.length" class="path-row empty" @click="addSource">
              <span class="path-icon"><AppIcon name="plus" :size="17" /></span><span class="path-text"><b>Add folders to organize</b><code>You can add several; read permission is checked before scanning</code></span>
            </button>
            <div class="route-option">
              <span><b>Include files in subfolders</b><small>{{ store.profile.includeSubfolders ? 'Looks through all subfolders level by level' : 'Only looks at the first level of the chosen folders' }}</small></span>
              <SwitchToggle v-model="store.profile.includeSubfolders" label="Include files in subfolders" />
            </div>
            <div class="route-label target">{{ fixedTarget ? 'Move to quarantine' : 'Organize into' }}</div>
            <div class="path-row target" :class="{ fixed: fixedTarget, error: targetInsideSource }">
              <span class="path-icon"><AppIcon :name="fixedTarget ? 'shield' : 'folder'" :size="17" /></span>
              <span class="path-text"><b>{{ targetName }}</b><code :title="targetPath">{{ targetPath }}</code></span>
              <span class="path-actions">
                <span v-if="fixedTarget" class="fixed-badge"><AppIcon name="lock" :size="13" />Managed by the app</span>
                <button v-else class="button ghost small" @click="changeTarget"><AppIcon name="swap" :size="14" />Change</button>
              </span>
            </div>
          </div>
        </section>

        <TypeRulesEditor v-if="isByType" :key="store.profile.id" v-model:expanded="expandedRule" :issues="issues" :target-name="targetName" />

        <section v-else-if="store.profile.presetType === 'old-installers'" class="panel config-section">
          <header class="section-head"><div class="section-title"><h2>Quarantine conditions</h2><p>Only handles installers such as dmg, pkg, exe, msi</p></div></header>
          <div class="option-list">
            <div class="option-row">
              <span><b>Installers unmodified for</b><small>Judged by last modified time</small></span>
              <div class="segments compact" role="radiogroup" aria-label="Days unmodified">
                <button v-for="days in [30, 60, 90, 180]" :key="days" role="radio" :aria-checked="params.olderThanDays === days" :class="{ active: params.olderThanDays === days }" @click="params.olderThanDays = days">{{ days }} days</button>
              </div>
            </div>
            <div class="option-row">
              <span><b>Also include ZIP archives</b><small>Archives may contain other files; off by default</small></span>
              <SwitchToggle :model-value="Boolean(params.includeArchives)" label="Also include ZIP archives" @update:model-value="params.includeArchives = $event" />
            </div>
          </div>
        </section>

        <section v-else-if="photos" class="panel config-section">
          <header class="section-head"><div class="section-title"><h2>What to scan</h2><p>Only reads photos. Deletions always go to quarantine and can be undone.</p></div></header>
          <div class="option-list">
            <div class="option-row">
              <span><b>Exact duplicates</b><small>Files are byte-for-byte identical, including two identical HEIC</small></span>
              <SwitchToggle :model-value="params.scanExact !== false" label="Exact duplicates" @update:model-value="params.scanExact = $event" />
            </div>
            <div class="option-row">
              <span><b>Looks similar</b><small>Copies that were compressed, differ in resolution, or were rotated or flipped</small></span>
              <SwitchToggle :model-value="params.scanSimilar !== false" label="Looks similar" @update:model-value="params.scanSimilar = $event" />
            </div>
            <div class="option-row">
              <span><b>Rotation and flipping</b><small>When on, rotated photos are grouped together; scanning is slower</small></span>
              <SwitchToggle :model-value="params.geometricInvariance !== false" label="Rotation and flipping" @update:model-value="params.geometricInvariance = $event" />
            </div>
            <div class="option-row">
              <span><b>Similarity strictness</b><small>The smaller the number, the less likely different photos are grouped together</small></span>
              <div class="segments compact" role="radiogroup" aria-label="Similarity distance">
                <button v-for="value in [0, 5, 10, 15]" :key="value" role="radio" :aria-checked="(params.maxDifference ?? 5) === value" :class="{ active: (params.maxDifference ?? 5) === value }" @click="params.maxDifference = value">{{ value }}</button>
              </div>
            </div>
          </div>
          <div class="banner undo inset"><AppIcon name="info" :size="16" />Similar groups are not pre-marked for deletion. After scanning you choose group by group, or apply a keep rule in one click and then adjust. macOS decodes HEIC with its built-in sips, so no extra decoder library is needed.</div>
        </section>

        <section v-else class="panel config-section">
          <header class="section-head"><div class="section-title"><h2>{{ store.profile.presetType === 'by-date' ? 'Archive by' : 'How to handle' }}</h2></div></header>
          <div v-if="store.profile.presetType === 'by-date'" class="banner quarantine inset"><AppIcon name="info" :size="16" />Archives by file modified date. The modified date isn’t always the date a photo was taken.</div>
          <div v-else class="banner undo inset"><AppIcon name="info" :size="16" />Duplicates found are never handled automatically. After scanning you pick which copy to keep for each group; the rest move to quarantine.</div>
        </section>
      </div>

      <aside class="config-aside">
        <section class="panel aside-card">
          <h3>This is how it will look</h3>
          <div class="tree">
            <div class="tree-root"><AppIcon :name="fixedTarget ? 'shield' : 'folder'" :size="15" /><b>{{ targetName }}/</b></div>
            <template v-if="isByType">
              <button v-for="{ rule, index } in enabledRules" :key="rule.id" class="tree-node" :class="`tone-${index % 8}`" @click="focusRule(rule.id)">
                <i class="tone-dot" /><span>{{ rule.folderName || '…' }}/</span><small>{{ rule.extensions.length }} kinds</small>
              </button>
              <div v-if="params.unmatchedAction !== 'keep'" class="tree-node muted"><i class="tone-dot" /><span>{{ params.otherFolder || '…' }}/</span><small>The rest</small></div>
              <p v-else class="tree-note">Unmatched files stay in place</p>
              <p v-if="!enabledRules.length && params.unmatchedAction === 'keep'" class="tree-note">No categories enabled yet</p>
            </template>
            <template v-else-if="store.profile.presetType === 'by-date'">
              <div class="tree-node"><i class="tone-dot" /><span>{{ now.getFullYear() }}/</span></div>
              <div class="tree-node deep"><i class="tone-dot" /><span>{{ now.getMonth() + 1 }}/</span></div>
            </template>
            <p v-else class="tree-note">Every file’s original location is recorded; restore in one click</p>
          </div>
        </section>

        <section class="panel aside-card">
          <h3>Pre-scan checks<span v-if="blockers" class="count-badge fail">{{ blockers }}</span></h3>
          <ul class="checklist">
            <li :class="store.profile.sourceFolders.length ? 'ok' : 'fail'">
              <AppIcon :name="store.profile.sourceFolders.length ? 'check' : 'alert'" :size="14" />
              {{ store.profile.sourceFolders.length ? `Selected ${store.profile.sourceFolders.length} source folders` : 'Add at least one source folder' }}
            </li>
            <li v-if="photos" :class="scanModeMissing ? 'fail' : 'ok'">
              <AppIcon :name="scanModeMissing ? 'alert' : 'check'" :size="14" />{{ scanModeMissing ? 'Turn on at least one of exact duplicates or similar' : 'Scan mode selected' }}
            </li>
            <li v-if="!fixedTarget" :class="targetInsideSource ? 'fail' : 'ok'">
              <AppIcon :name="targetInsideSource ? 'alert' : 'check'" :size="14" />{{ targetInsideSource ? 'The target folder is inside the source; please change it' : 'The target folder is not inside the source' }}
            </li>
            <template v-if="isByType">
              <li v-if="!issues.length" class="ok"><AppIcon name="check" :size="14" />No conflicts in category rules</li>
              <li v-for="(issue, index) in issues" :key="index" class="fail" :class="{ link: issue.ruleId }" @click="focusRule(issue.ruleId)">
                <AppIcon name="alert" :size="14" />
                <span><b v-if="issue.ruleId">{{ params.typeRules?.find((rule) => rule.id === issue.ruleId)?.name || 'Unnamed category' }}</b>{{ issue.message }}</span>
              </li>
            </template>
            <li v-for="(issue, index) in environmentIssues" :key="`env-${index}`" class="fail"><AppIcon name="alert" :size="14" /><span>{{ serverLabel(issue) }}</span></li>
          </ul>
        </section>

        <section class="panel aside-card subtle">
          <h3>Auto-skipped</h3>
          <p>Files still downloading, system files, symlinks, and files that cannot be read safely.</p>
        </section>
      </aside>
    </div>

    <footer class="action-bar config-actions">
      <button class="button secondary" @click="store.go('home')">← Back to home</button>
      <span class="action-summary" :class="{ fail: blockers }">
        <template v-if="blockers"><AppIcon name="alert" :size="15" />{{ blockers }} issues to fix before scanning</template>
        <template v-else><AppIcon name="check" :size="15" />{{ summary }}</template>
      </span>
      <button class="button primary" :disabled="validating || store.busy || blockers > 0" @click="scan">{{ validating ? 'Checking…' : 'Start scan' }}<AppIcon name="arrow" :size="16" /></button>
    </footer>
  </div>
</template>
