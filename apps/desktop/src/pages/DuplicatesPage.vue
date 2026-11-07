<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { localFileUrl } from '../api'
import { useAppStore } from '../stores/app'
import { fileName, formatBytes } from '../utils'
import type { KeepRule, PlanItem } from '../types'

const store = useAppStore()
const confirm = ref(false)
const thumbs = ref<Record<string, string>>({})
const photos = computed(() => store.profile.presetType === 'similar-photos')
const groups = computed(() => {
  const result = new Map<string, PlanItem[]>()
  for (const item of store.plan?.items ?? []) {
    const key = item.groupId ?? 'unknown'
    if (!result.has(key)) result.set(key, [])
    result.get(key)!.push(item)
  }
  return [...result.entries()]
})
const decided = computed(() => groups.value.filter(([, items]) => items.some((item) => item.metadata.decision === 'keep')).length)
const warnings = computed(() => store.plan?.summary.warnings ?? [])
const rules: Array<{ id: KeepRule; label: string }> = [
  { id: 'resolution', label: 'Keep highest resolution' },
  { id: 'largest', label: 'Keep largest file' },
  { id: 'newest', label: 'Keep most recently modified' },
  { id: 'shortest', label: 'Keep shortest path' },
]
const ruleNames: Record<KeepRule, string> = {
  resolution: 'Highest resolution',
  largest: 'Largest file',
  newest: 'Most recently modified',
  shortest: 'Shortest path',
}

function pixels(item: PlanItem) {
  return Number(item.metadata.width ?? 0) * Number(item.metadata.height ?? 0)
}
function better(candidate: PlanItem, current: PlanItem, rule: KeepRule) {
  const rank = (item: PlanItem) => {
    const area = pixels(item)
    const modified = Number(item.metadata.modifiedMs ?? 0)
    if (rule === 'largest') return [item.size, area, modified, -item.sourcePath.length]
    if (rule === 'newest') return [modified, area, item.size, -item.sourcePath.length]
    if (rule === 'shortest') return [-item.sourcePath.length, area, item.size, modified]
    return [area, item.size, modified, -item.sourcePath.length]
  }
  const left = rank(candidate)
  const right = rank(current)
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return left[index] > right[index]
  }
  return candidate.sourcePath < current.sourcePath
}
function applyRule(rule: KeepRule) {
  for (const [groupId, items] of groups.value) {
    const keep = items.reduce((chosen, item) => better(item, chosen, rule) ? item : chosen)
    store.selectDuplicateKeep(groupId, keep.itemId)
  }
}
function applyRecommended() {
  for (const [groupId, items] of groups.value) {
    const keep = items.find((item) => item.metadata.recommendedKeep)
    if (keep) store.selectDuplicateKeep(groupId, keep.itemId)
  }
}
function kindLabel(items: PlanItem[]) {
  return items.some((item) => item.metadata.kind === 'similar') ? 'similar' : 'identical'
}
watch(() => store.plan?.planId, async () => {
  const next: Record<string, string> = {}
  for (const item of store.plan?.items ?? []) {
    const path = String(item.metadata.previewPath || item.sourcePath || '')
    if (path) next[item.itemId] = await localFileUrl(path)
  }
  thumbs.value = next
}, { immediate: true })
</script>

<template>
  <div class="page scroll-page duplicate-page">
    <header class="page-header">
      <div>
        <h1>{{ photos ? 'Choose which photo to keep in each group' : 'Choose which file to keep in each group' }}</h1>
        <p>{{ photos ? 'Similar photos are not marked for deletion by default. Pick one to keep per group, or mark them all at once with a rule, then adjust one by one.' : 'Only files with identical content appear here. Nothing is processed until you choose.' }}</p>
      </div>
      <div class="rule-actions" v-if="photos">
        <button v-for="rule in rules" :key="rule.id" class="button secondary" @click="applyRule(rule.id)">{{ rule.label }}</button>
      </div>
      <button v-else class="button secondary" @click="applyRecommended">Use all recommendations</button>
    </header>
    <p v-if="warnings.length" class="banner undo inset scan-warning">{{ warnings.includes('HEIC_DECODE_UNAVAILABLE') ? 'This computer can’t decode HEIC, so similarity comparison skips those photos; byte-identical HEIC files are still listed.' : warnings[0] }}</p>
    <section class="summary-card compact">
      <div><strong>{{ groups.length }}</strong><span>{{ photos ? 'photo groups' : 'duplicate groups' }}</span></div>
      <div class="dup-stats"><span>Decided <b>{{ decided }} / {{ groups.length }}</b></span><span>Will go to quarantine <b>{{ store.selectedItems.length }}</b></span></div>
    </section>
    <section v-if="!groups.length" class="empty-state">
      <h2>{{ photos ? 'No duplicate or similar photos found' : 'No duplicate files found' }}</h2>
      <p>No files were moved. You can go back and change folders or scan options.</p>
    </section>
    <section v-for="([groupId, items], index) in groups" :key="groupId" class="panel duplicate-group" :class="{ undecided: !items.some((item) => item.metadata.decision === 'keep') }">
      <div class="panel-title">
        <span>Group {{ index + 1 }} · {{ items.length }} {{ kindLabel(items) }} files</span>
        <span class="op-badge" :class="items.some((item) => item.metadata.decision === 'keep') ? 'ok' : 'warn'">{{ items.some((item) => item.metadata.decision === 'keep') ? 'Decided' : 'Please choose which copy to keep' }}</span>
      </div>
      <div v-if="photos" class="photo-grid">
        <button v-for="item in items" :key="item.itemId" class="photo-card" :class="{ keep: item.metadata.decision === 'keep' }" @click="store.selectDuplicateKeep(groupId, item.itemId)">
          <img v-if="thumbs[item.itemId]" :src="thumbs[item.itemId]" :alt="fileName(item.sourcePath)" />
          <span v-else class="photo-fallback">{{ fileName(item.sourcePath) }}</span>
          <span class="photo-meta">
            <b>{{ fileName(item.sourcePath) }}</b>
            <small>{{ item.sourcePath }}</small>
            <small>{{ item.metadata.width && item.metadata.height ? `${item.metadata.width}×${item.metadata.height} · ` : '' }}{{ formatBytes(item.size) }}{{ item.metadata.kind === 'similar' ? ` · Distance ${item.metadata.difference ?? 0}` : '' }}</small>
          </span>
          <strong>{{ item.metadata.decision === 'keep' ? 'Keep' : item.metadata.decision === 'quarantine' ? 'Go to quarantine' : 'To be chosen' }}</strong>
          <em v-if="item.metadata.recommendedKeep">Recommended: {{ ruleNames[(item.metadata.recommendedRule as KeepRule) || 'resolution'] }}</em>
        </button>
      </div>
      <button v-else v-for="item in items" :key="item.itemId" class="duplicate-row" @click="store.selectDuplicateKeep(groupId, item.itemId)">
        <span class="radio" :class="{ on: item.metadata.decision === 'keep' }" /><span><b>{{ fileName(item.sourcePath) }}</b><small>{{ item.sourcePath }}</small></span><span v-if="item.metadata.recommendedKeep" class="op-badge undo">Recommended to keep: the earliest copy</span><strong>{{ item.metadata.decision === 'keep' ? 'Keep' : item.metadata.decision === 'quarantine' ? 'Go to quarantine' : 'To be chosen' }}</strong>
      </button>
    </section>
    <footer class="action-bar">
      <button class="button secondary" @click="store.go('config')">← Back to edit plan</button>
      <span>{{ !groups.length ? 'No files need quarantining.' : decided < groups.length ? `${groups.length - decided} groups have no kept item selected.` : `Will quarantine ${store.selectedItems.length} files.` }}</span>
      <button class="button primary" :disabled="!groups.length || decided < groups.length" @click="confirm = true">Quarantine {{ store.selectedItems.length }} files</button>
    </footer>
    <div v-if="confirm" class="modal-backdrop" @click.self="confirm = false">
      <section class="dialog">
        <h2>Quarantine {{ store.selectedItems.length }} files?</h2>
        <p>Kept items are not changed. The rest go to quarantine and can be restored. Nothing is permanently deleted or sent to the system Trash.</p>
        <div><button class="button secondary" @click="confirm = false">Look again</button><button class="button primary" @click="confirm = false; store.executePlan()">Start organizing</button></div>
      </section>
    </div>
  </div>
</template>
