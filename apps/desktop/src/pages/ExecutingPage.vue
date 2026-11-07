<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { fileName } from '../utils'
import CareVisual from '../components/CareVisual.vue'

const store = useAppStore()
const stopping = ref(false)
const total = computed(() => store.selectedItems.length)
const percent = computed(() => total.value ? Math.min(100, Math.round(store.runCompleted / total.value * 100)) : 0)
async function stop() { stopping.value = true; await store.cancelRun() }
</script>

<template>
  <div class="page execution-page" aria-busy="true">
    <section class="execution-card">
      <CareVisual mode="working" :progress="percent" />
      <header><h1>{{ stopping ? 'Stopping safely' : 'Files are going where they belong' }}</h1></header>
      <div class="progress" role="progressbar" aria-label="Progress" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"><i :class="{ stopping }" :style="{ width: `${percent}%` }" /></div>
      <div class="progress-meta"><span>{{ store.runCompleted }} / {{ total }} files</span><span>{{ stopping ? 'Will stop after the current file finishes' : 'Please keep the app running' }}</span></div>
      <div class="current-file"><small>{{ stopping ? 'Finishing the current file' : 'Current file' }}</small><b>{{ fileName(store.runCurrent) || 'Preparing…' }}</b><code>{{ store.runCurrent }}</code></div>
      <div v-if="stopping" class="banner warn">Finishing the current file, then stopping. Stopping midway could leave an incomplete file, so it is completed safely first.</div>
      <div class="stat-grid"><div><strong>{{ store.runSuccess }}</strong><span>Completed</span></div><div><strong>{{ store.runSkipped }}</strong><span>Skipped</span></div><div><strong>{{ store.runFailed }}</strong><span>Failed</span></div></div>
      <p>Existing files are never overwritten. Every step is recorded in the history.</p>
    </section>
    <footer class="action-bar"><span /><span>Completed files can be undone from the history.</span><button class="button danger" :disabled="stopping" @click="stop">{{ stopping ? 'Stopping…' : 'Stop organizing' }}</button></footer>
  </div>
</template>
