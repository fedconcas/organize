<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '../stores/app'
import { formatBytes } from '../utils'
import CareVisual from '../components/CareVisual.vue'

const store = useAppStore()
const title = computed(() => {
  if (!store.result) return 'Organizing finished'
  if (store.result.status === 'completed') return `Organizing finished, ${store.result.success} files processed`
  if (store.result.status === 'cancelled') return `Organizing stopped, ${store.result.success} files completed`
  return `Organizing finished, ${store.result.failed} files did not succeed`
})
</script>

<template>
  <div v-if="store.result" class="page result-page">
    <section class="result-hero"><CareVisual v-if="store.result.status === 'completed'" mode="success" /><span v-else :class="store.result.status">!</span><div><span class="eyebrow">{{ store.result.status === 'completed' ? 'A LITTLE MORE ORDER' : 'YOUR FILES, YOUR CONTROL' }}</span><h1>{{ title }}</h1><p>Files that did not succeed stay in place with no extra changes.</p></div></section>
    <div class="result-stats"><div><strong>{{ store.result.success }}</strong><span>Completed</span></div><div><strong>{{ store.result.skipped }}</strong><span>Skip</span></div><div><strong>{{ store.result.failed }}</strong><span>Failed</span></div><div><strong>{{ formatBytes(store.result.successBytes ?? 0) }}</strong><span>Size processed</span></div></div>
    <div class="result-grid"><section class="panel"><div class="panel-title">Result</div><div class="empty-success">✓ Every successful action has been written to the history.</div></section><section class="panel undo-card"><div class="panel-title">↶ This run can be undone</div><div class="panel-body"><p>A preview is shown before undoing; you can restore only some files.</p></div><button class="button undo" @click="store.prepareUndo(store.result.runId)">Undo this run</button></section></div>
    <footer class="action-bar"><button class="button secondary" @click="store.go('home')">Back to home</button><button class="button ghost" @click="store.go('config')">Run again</button><span /><button class="button primary" @click="store.go('history')">View organizing records</button></footer>
  </div>
</template>
