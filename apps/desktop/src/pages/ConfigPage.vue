<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { pickDirectories } from '../api'
import { hasAiRules, ruleIssues, ruleKind, stableStringify, type RuleIssue } from '../profiles'
import AppIcon from '../components/AppIcon.vue'
import ProfileMenu from '../components/ProfileMenu.vue'
import SwitchToggle from '../components/SwitchToggle.vue'
import TypeRulesEditor from '../components/TypeRulesEditor.vue'

const store = useAppStore()
const validating = ref(false)
const serverIssues = ref<Array<Record<string, unknown>>>([])
const expandedRule = ref<string>()
const confirmRepropose = ref(false)
const aiRules = computed(() => hasAiRules(store.profile))

const PRESETS = {
  'by-type': { label: 'Sort by type', icon: 'folder', description: 'Puts files into matching subfolders by extension.' },
  'by-date': { label: 'Archive by date', icon: 'image', description: 'Puts photos into “Year/Month” folders by the date they were taken.' },
  'old-installers': { label: 'Clean up old installers', icon: 'download', description: 'Move long-unused installers to quarantine; restore any time.' },
  duplicates: { label: 'Duplicate file finder', icon: 'duplicate', description: 'Finds files with identical content; you decide which copy to keep.' },
} as const
const preset = computed(() => PRESETS[store.profile.presetType])
const params = computed(() => store.profile.parameters)
const isByType = computed(() => store.profile.presetType === 'by-type')
const fixedTarget = computed(() => ['old-installers', 'duplicates'].includes(store.profile.presetType))
const useDateTaken = computed(() => params.value.dateSource !== 'modified')
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
  INVALID_RULE_KIND: 'Unknown kind of category', INVALID_RULE_MATCH: 'Category matching details are invalid',
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
const blockers = computed(() => (store.profile.sourceFolders.length ? 0 : 1) + (targetInsideSource.value ? 1 : 0) + issues.value.length)

const enabledRules = computed(() => (params.value.typeRules ?? []).map((rule, index) => ({ rule, index })).filter(({ rule }) => rule.enabled))
const now = new Date()
const summary = computed(() => {
  const sources = `${store.profile.sourceFolders.length} sources`
  if (isByType.value) return `${sources} → ${enabledRules.value.length} categories${params.value.unmatchedAction === 'keep' ? ', unmatched files stay in place' : ''}`
  if (store.profile.presetType === 'by-date') return `${sources} → Archive by “Year/Month” of the ${useDateTaken.value ? 'date taken' : 'modified date'}`
  if (store.profile.presetType === 'old-installers') return `${sources} → Installers older than ${params.value.olderThanDays ?? 90} days are moved to quarantine`
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

        <div v-if="isByType && !store.settings.aiEnabled && !aiRules" class="banner quarantine inset ai-off-note"><AppIcon name="info" :size="16" />Files are sorted by extension, as before. Local AI categories are off; turn on “Local AI” in Settings to have Organize propose categories from your files.</div>
        <div v-if="isByType && aiRules && !store.settings.aiEnabled" class="banner warn inset ai-off-note"><AppIcon name="alert" :size="16" />Local AI is off: files that only a content category could match go to “{{ params.otherFolder || 'Other files' }}”.</div>
        <div v-if="isByType && (store.settings.aiEnabled || aiRules)" class="repropose-row">
          <span>{{ aiRules ? 'These categories were proposed from your files and saved for future scans.' : 'Let Organize look at your files and propose categories.' }}</span>
          <button class="text-button" :disabled="store.busy" @click="aiRules ? (confirmRepropose = true) : store.reproposeCategories()">{{ aiRules ? 'Re-propose' : 'Propose categories' }}</button>
        </div>
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

        <section v-else class="panel config-section">
          <header class="section-head"><div class="section-title"><h2>{{ store.profile.presetType === 'by-date' ? 'Archive by' : 'How to handle' }}</h2></div></header>
          <div v-if="store.profile.presetType === 'by-date'" class="option-list">
            <div class="option-row">
              <span><b>Use date taken when available</b><small>Read from the photo’s EXIF header. Photos without one use the file’s modified date; the preview shows which date each photo used.</small></span>
              <SwitchToggle :model-value="useDateTaken" label="Use date taken when available" @update:model-value="params.dateSource = $event ? 'taken' : 'modified'" />
            </div>
          </div>
          <div v-if="store.profile.presetType === 'by-date'" class="banner quarantine inset"><AppIcon name="info" :size="16" />{{ useDateTaken ? 'Archives by the date taken, falling back to the modified date. Location and camera details are never stored.' : 'Archives by file modified date. The modified date isn’t always the date a photo was taken.' }}</div>
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
                <i class="tone-dot" /><span>{{ rule.folderName || '…' }}/</span><small>{{ ruleKind(rule) === 'content' ? 'by content' : ruleKind(rule) === 'metadata' ? 'photo details' : `${rule.extensions.length} kinds` }}</small>
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

    <div v-if="confirmRepropose" class="modal-backdrop" @click.self="confirmRepropose = false">
      <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="repropose-title">
        <h2 id="repropose-title">Replace the current categories?</h2>
        <p>Organize will look at the folders again and propose new categories. When you accept them, they replace the {{ params.typeRules?.length ?? 0 }} categories of this plan and their saved matching data. Files are not moved.</p>
        <div><button class="button secondary" @click="confirmRepropose = false">Keep current</button><button class="button primary" @click="confirmRepropose = false; store.reproposeCategories()">Re-propose</button></div>
      </section>
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
