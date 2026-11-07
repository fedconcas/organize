<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { fileName } from '../utils'
import type { PlanItem } from '../types'

const store = useAppStore()
const confirm = ref(false)
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
function applyRecommended() {
  for (const [groupId, items] of groups.value) {
    const keep = items.find((item) => item.metadata.recommendedKeep)
    if (keep) store.selectDuplicateKeep(groupId, keep.itemId)
  }
}
</script>

<template>
  <div class="page scroll-page duplicate-page">
    <header class="page-header">
      <div>
        <h1>Choose which file to keep in each group</h1>
        <p>Only files with identical content appear here. Nothing is processed until you choose.</p>
      </div>
      <button class="button secondary" @click="applyRecommended">Use all recommendations</button>
    </header>
    <section class="summary-card compact">
      <div><strong>{{ groups.length }}</strong><span>duplicate groups</span></div>
      <div class="dup-stats"><span>Decided <b>{{ decided }} / {{ groups.length }}</b></span><span>Will go to quarantine <b>{{ store.selectedItems.length }}</b></span></div>
    </section>
    <section v-if="!groups.length" class="empty-state">
      <h2>No duplicate files found</h2>
      <p>No files were moved. You can go back and change folders or scan options.</p>
    </section>
    <section v-for="([groupId, items], index) in groups" :key="groupId" class="panel duplicate-group" :class="{ undecided: !items.some((item) => item.metadata.decision === 'keep') }">
      <div class="panel-title">
        <span>Group {{ index + 1 }} · {{ items.length }} identical files</span>
        <span class="op-badge" :class="items.some((item) => item.metadata.decision === 'keep') ? 'ok' : 'warn'">{{ items.some((item) => item.metadata.decision === 'keep') ? 'Decided' : 'Please choose which copy to keep' }}</span>
      </div>
      <button v-for="item in items" :key="item.itemId" class="duplicate-row" @click="store.selectDuplicateKeep(groupId, item.itemId)">
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
