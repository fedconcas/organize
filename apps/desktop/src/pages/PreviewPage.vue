<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { formatBytes } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import PlanTable from '../components/PlanTable.vue'

const store = useAppStore()
const confirming = ref(false)
const selected = computed(() => store.selectedItems.length)
const conflicts = computed(() => store.plan?.items.filter((item) => item.warningCode === 'TARGET_CONFLICT').length ?? 0)
const isByType = computed(() => store.plan?.profile.presetType === 'by-type')
const categories = computed(() => {
  if (!isByType.value || !store.plan) return undefined
  const params = store.plan.profile.parameters
  const rules = (params.typeRules ?? []).filter((rule) => rule.enabled).map((rule) => ({ id: rule.id, name: rule.name }))
  return params.unmatchedAction === 'keep' ? rules : [...rules, { id: 'other', name: params.otherFolder || 'Other files' }]
})
const pendingHigh = computed(() => store.plan?.items.filter((item) => ['content', 'analysis'].includes(String(item.metadata.source)) && item.metadata.confidence === 'high' && !item.selected && item.status !== 'skipped').length ?? 0)
const pendingMedium = computed(() => store.plan?.items.filter((item) => ['content', 'analysis'].includes(String(item.metadata.source)) && item.metadata.confidence === 'medium' && !item.selected && item.status !== 'skipped').length ?? 0)
const suggestions = computed(() => store.plan?.items.filter((item) => ['content', 'analysis'].includes(String(item.metadata.source))).length ?? 0)
const AI_NOTICES: Record<string, string> = {
  AI_DISABLED: 'Local AI is off, so files that only a content category could match go to the Other folder.',
  AI_UNAVAILABLE: 'The local AI model was not available, so some files could not be matched to content categories and go to the Other folder.',
}
</script>

<template>
  <div v-if="store.plan" class="page flow-page">
    <PageHeader title="Confirm organizing plan" description="Only the files checked below will be organized; files added after the scan are not processed." />
    <section class="summary-card">
      <div><strong>{{ selected.toLocaleString() }}</strong><span>files will be organized, totaling {{ formatBytes(store.selectedBytes) }}</span></div>
      <div class="summary-details">
        <div class="plan-bar"><i class="move" :style="{ flex: Math.max(1, selected) }" /><i class="warn" :style="{ flex: conflicts }" /><i class="skip" :style="{ flex: store.plan.summary.skip }" /></div>
        <div class="legend"><span>■ Move <b>{{ store.plan.summary.move }}</b></span><span class="warn-text">■ Name clash <b>{{ conflicts }}</b></span><span>■ Skip <b>{{ store.plan.summary.skip }}</b></span><span>■ Excluded by you <b>{{ store.plan.items.filter((x) => !x.selected && x.status !== 'skipped').length }}</b></span></div>
      </div>
    </section>
    <div v-if="conflicts" class="banner warn"><b>{{ conflicts }} files have the same name as files at the destination.</b>They automatically get new names; existing files are never overwritten.</div>
    <div v-if="store.plan.summary.aiNotice" class="banner quarantine inset">{{ AI_NOTICES[store.plan.summary.aiNotice] ?? store.plan.summary.aiNotice }}</div>
    <div v-if="suggestions" class="banner undo suggestion-bar">
      <span><b>{{ suggestions }} files were sorted by content.</b> Suggestions below High confidence start unchecked; check them or pick another category.</span>
      <span class="suggestion-actions">
        <button class="button secondary small" :disabled="!pendingHigh" @click="store.acceptSuggestions('high')">Accept all high-confidence ({{ pendingHigh }})</button>
        <button class="button secondary small" :disabled="!pendingMedium" @click="store.acceptSuggestions('medium')">Also accept medium ({{ pendingMedium }})</button>
      </span>
    </div>
    <PlanTable :items="store.plan.items" :categories="categories" @toggle="store.toggleItem" @set-category="store.setItemCategory" />
    <footer class="action-bar"><button class="button secondary" @click="store.go('config')">← Back to edit plan</button><span>Selected <b>{{ selected }}</b> files, {{ formatBytes(store.selectedBytes) }}. No files are deleted or overwritten.</span><button class="button primary" :disabled="!selected" @click="confirming = true">Organize {{ selected }} files</button></footer>
    <div v-if="confirming" class="modal-backdrop" @click.self="confirming = false">
      <section class="dialog"><h2>Organize {{ selected }} files?</h2><p>These files will be moved to “{{ store.profile.targetFolder }}”. Files with the same name are renamed automatically and nothing is overwritten. You can undo after it finishes.</p><div><button class="button secondary" @click="confirming = false">Look again</button><button class="button primary" @click="confirming = false; store.executePlan()">Start organizing</button></div></section>
    </div>
  </div>
</template>
