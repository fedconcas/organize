<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { CLASSIFICATION_TEMPLATES, classificationTemplate, ensureClassification, extensionOwners, newRuleName, ruleKind, type RuleIssue } from '../profiles'
import type { TypeRule } from '../types'
import AppIcon from './AppIcon.vue'
import ExtensionInput from './ExtensionInput.vue'
import SwitchToggle from './SwitchToggle.vue'

const props = defineProps<{ issues: RuleIssue[]; targetName: string }>()
const expanded = defineModel<string | undefined>('expanded')
const store = useAppStore()
ensureClassification(store.profile)

const rules = computed(() => store.profile.parameters.typeRules ?? [])
const owners = computed(() => extensionOwners(rules.value))
const enabledCount = computed(() => rules.value.filter((rule) => rule.enabled).length)
const extensionCount = computed(() => rules.value.filter((rule) => rule.enabled).reduce((sum, rule) => sum + rule.extensions.length, 0))
const unmatched = computed({
  get: () => store.profile.parameters.unmatchedAction ?? 'other',
  set: (value) => { store.profile.parameters.unmatchedAction = value },
})
const issuesFor = (id?: string, field?: RuleIssue['field']) => props.issues.filter((issue) => issue.ruleId === id && (!field || issue.field === field))
const otherIssue = computed(() => props.issues.find((issue) => issue.field === 'other'))

function conflictsFor(rule: TypeRule) {
  const result = new Map<string, string[]>()
  if (!rule.enabled) return result
  for (const extension of rule.extensions) {
    const others = (owners.value.get(extension) ?? []).filter((name) => name !== (rule.name || 'Unnamed category'))
    if (others.length) result.set(extension, others)
  }
  return result
}

const ICONS: Array<[RegExp, string]> = [
  [/^(documents|text|pdf|sheets|slides)$|documents?|text|materials?|spreadsheets?|presentations?/i, 'file'],
  [/^(images|photos|graphics)$|images?|photos?|graphics/i, 'image'],
  [/^videos$|videos?/i, 'video'],
  [/^audio$|audio/i, 'music'],
  [/^archives$|archives?/i, 'archive'],
  [/^installers$|installers?/i, 'package'],
]
const iconFor = (rule: TypeRule) => ICONS.find(([pattern]) => pattern.test(rule.id) || pattern.test(rule.name))?.[1] ?? 'tag'

const KIND_BADGES = { content: 'AI · content', metadata: 'Photo details', extension: '' } as const
function toggle(id: string) { expanded.value = expanded.value === id ? undefined : id }
function rename(rule: TypeRule, value: string) {
  if (rule.folderName === rule.name) rule.folderName = value
  rule.name = value
}
async function add() {
  const name = newRuleName(rules.value)
  const rule: TypeRule = { id: crypto.randomUUID(), name, folderName: name, extensions: [], enabled: true }
  store.profile.parameters.typeRules = [...rules.value, rule]
  expanded.value = rule.id
  await nextTick()
  document.querySelector<HTMLInputElement>(`[data-rule-name="${rule.id}"]`)?.select()
}
function remove(rule: TypeRule) {
  store.profile.parameters.typeRules = rules.value.filter((item) => item.id !== rule.id)
  expanded.value = undefined
}

const templateOpen = ref(false)
const pendingTemplate = ref<string>()
const templateRoot = ref<HTMLElement>()
function closeTemplates() { templateOpen.value = false; pendingTemplate.value = undefined }
function applyTemplate(id: string) {
  store.profile.parameters.typeRules = classificationTemplate(id)
  expanded.value = undefined
  closeTemplates()
}
function onDocumentClick(event: MouseEvent) { if (!templateRoot.value?.contains(event.target as Node)) closeTemplates() }
onMounted(() => document.addEventListener('mousedown', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))
</script>

<template>
  <section class="panel config-section rules-panel">
    <header class="section-head">
      <div class="section-title">
        <h2>Category rules</h2>
        <p>{{ enabledCount }} categories enabled, recognizing {{ extensionCount }} extensions</p>
      </div>
      <div class="section-actions">
        <div ref="templateRoot" class="menu-anchor">
          <button class="button secondary small" :aria-expanded="templateOpen" @click="templateOpen ? closeTemplates() : (templateOpen = true)"><AppIcon name="layers" :size="15" />Apply template<AppIcon name="chevron" :size="13" /></button>
          <div v-if="templateOpen" class="popover template-menu" role="menu">
            <header class="popover-head">Start from a template</header>
            <template v-for="template in CLASSIFICATION_TEMPLATES" :key="template.id">
              <button v-if="pendingTemplate !== template.id" role="menuitem" class="template-item" @click="pendingTemplate = template.id">
                <span><b>{{ template.name }}</b><small>{{ template.description }}</small></span>
                <em>{{ classificationTemplate(template.id).length }} categories</em>
              </button>
              <div v-else class="template-confirm">
                <p>Use “{{ template.name }}” to replace the current {{ rules.length }} categories? Sources and destination stay unchanged.</p>
                <div><button class="text-button" @click="pendingTemplate = undefined">Cancel</button><button class="button primary small" @click="applyTemplate(template.id)">Replace</button></div>
              </div>
            </template>
          </div>
        </div>
        <button class="button secondary small" @click="add"><AppIcon name="plus" :size="15" />Add category</button>
      </div>
    </header>

    <div class="rule-table" role="list">
      <div class="rule-head" aria-hidden="true"><span>Enabled</span><span>Category</span><span>Put in</span><span>Extensions</span></div>
      <article v-for="(rule, index) in rules" :key="rule.id" role="listitem" class="rule-row" :class="[`tone-${index % 8}`, { off: !rule.enabled, open: expanded === rule.id, invalid: issuesFor(rule.id).length }]" :data-rule="rule.id">
        <div class="rule-summary" @click="toggle(rule.id)">
          <SwitchToggle v-model="rule.enabled" :label="`Enable category ${rule.name}`" />
          <span class="rule-name"><i class="rule-glyph"><AppIcon :name="iconFor(rule)" :size="15" /></i><b>{{ rule.name || 'Unnamed category' }}</b></span>
          <code class="rule-folder" :title="`${targetName}/${rule.folderName}`"><i>{{ targetName }}/</i>{{ rule.folderName || '…' }}</code>
          <span v-if="ruleKind(rule) === 'content'" class="rule-exts"><em class="kind-badge content">{{ KIND_BADGES.content }}</em><span class="ext-empty">Matched by what the files contain</span></span>
          <span v-else class="rule-exts">
            <em v-if="ruleKind(rule) === 'metadata'" class="kind-badge metadata">{{ KIND_BADGES.metadata }}</em>
            <span v-for="extension in rule.extensions.slice(0, 6)" :key="extension" class="ext-chip mini" :class="{ conflict: conflictsFor(rule).has(extension) }">{{ extension }}</span>
            <span v-if="rule.extensions.length > 6" class="ext-more">+{{ rule.extensions.length - 6 }}</span>
            <span v-if="!rule.extensions.length" class="ext-empty">No extensions set</span>
          </span>
          <span class="rule-state" :title="issuesFor(rule.id)[0]?.message">
            <AppIcon v-if="rule.enabled && issuesFor(rule.id).length" name="alert" :size="15" />
          </span>
          <button class="icon-button chevron" :aria-expanded="expanded === rule.id" :aria-label="`Edit category ${rule.name}`" @click.stop="toggle(rule.id)"><AppIcon name="chevron" :size="16" /></button>
        </div>
        <div v-if="expanded === rule.id" class="rule-editor">
          <label class="field" :class="{ error: issuesFor(rule.id, 'name').length }">
            <span>Category name</span>
            <input :value="rule.name" :data-rule-name="rule.id" maxlength="80" @input="rename(rule, ($event.target as HTMLInputElement).value)" />
            <small v-for="issue in issuesFor(rule.id, 'name')" :key="issue.message">{{ issue.message }}</small>
          </label>
          <label class="field" :class="{ error: issuesFor(rule.id, 'folder').length }">
            <span>Put in subfolder</span>
            <span class="prefixed-input"><em>{{ targetName }}/</em><input v-model="rule.folderName" maxlength="120" /></span>
            <small v-for="issue in issuesFor(rule.id, 'folder')" :key="issue.message">{{ issue.message }}</small>
          </label>
          <p v-if="ruleKind(rule) !== 'extension'" class="field wide kind-note">{{ ruleKind(rule) === 'content' ? 'Files are matched to this category by their content, using the examples you accepted. Matching happens on this Mac.' : 'Photos are matched by their details (date taken, camera, screenshot). Location and camera details are not stored.' }}</p>
          <div v-else class="field wide" :class="{ error: issuesFor(rule.id, 'extensions').length }">
            <span>Extensions<em>Press Enter, Space or comma to confirm; Backspace removes the last one</em></span>
            <ExtensionInput v-model="rule.extensions" :label="`${rule.name} extensions`" :conflicts="conflictsFor(rule)" />
            <small v-for="issue in issuesFor(rule.id, 'extensions')" :key="issue.message">{{ issue.message }}</small>
          </div>
          <footer class="rule-editor-actions">
            <button class="text-button danger" @click="remove(rule)"><AppIcon name="trash" :size="14" />Delete this category</button>
            <button class="button secondary small" @click="expanded = undefined">Done</button>
          </footer>
        </div>
      </article>

      <article class="rule-row fallback" :class="{ invalid: otherIssue }">
        <div class="rule-summary static">
          <span class="fallback-mark"><AppIcon name="info" :size="15" /></span>
          <span class="rule-name"><b>Unmatched files</b><small>Files that don’t belong to any enabled category</small></span>
          <div class="segments compact" role="radiogroup" aria-label="How to handle unmatched files">
            <button role="radio" :aria-checked="unmatched === 'other'" :class="{ active: unmatched === 'other' }" @click="unmatched = 'other'">Move into a folder</button>
            <button role="radio" :aria-checked="unmatched === 'keep'" :class="{ active: unmatched === 'keep' }" @click="unmatched = 'keep'">Stay in place</button>
          </div>
          <span v-if="unmatched === 'other'" class="prefixed-input small" :class="{ error: otherIssue }" :title="otherIssue?.message">
            <em>{{ targetName }}/</em><input v-model="store.profile.parameters.otherFolder" maxlength="120" aria-label="Other folder name" />
          </span>
          <span v-else class="fallback-note">Won’t be moved</span>
        </div>
      </article>
    </div>
  </section>
</template>
