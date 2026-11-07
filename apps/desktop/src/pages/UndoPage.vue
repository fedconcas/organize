<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { useAppStore } from '../stores/app'
import { fileName, formatBytes } from '../utils'
import PageHeader from '../components/PageHeader.vue'

const store = useAppStore()
const selected = ref(new Set<string>())
watchEffect(() => {
  selected.value = new Set(
    (store.undoPreview?.items ?? []).filter((item) => item.selected).map((item) => item.operationId),
  )
})
const items = computed(() => store.undoPreview?.items ?? [])
const restorable = computed(() => items.value.filter((item) => ['ready', 'rename'].includes(item.state)))
function toggle(id: string) {
  const next = new Set(selected.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selected.value = next
}
</script>

<template>
  <div class="page scroll-page undo-page">
    <PageHeader title="Undo preview" description="Only the files selected below are restored. Files that changed or can’t be found are left as they are." />
    <section class="summary-card compact">
      <div><strong>{{ restorable.length }}</strong><span>can be restored</span></div>
      <div><strong>{{ items.length - restorable.length }}</strong><span>to be left as they are</span></div>
      <div><strong>{{ formatBytes(items.filter(item => selected.has(item.operationId)).reduce((n, item) => n + item.size, 0)) }}</strong><span>This restore</span></div>
    </section>
    <section class="panel undo-list">
      <button v-for="item in items" :key="item.operationId" :disabled="!['ready','rename'].includes(item.state)" @click="toggle(item.operationId)">
        <span class="check" :class="{ on: selected.has(item.operationId) }">{{ selected.has(item.operationId) ? '✓' : '' }}</span>
        <span><b>{{ fileName(item.currentPath) }}</b><small>{{ item.currentPath }} → {{ item.restorePath }}</small></span>
        <span class="op-badge" :class="item.state === 'ready' ? 'ok' : item.state === 'rename' ? 'warn' : 'fail'">
          {{ item.state === 'ready' ? 'Restorable' : item.state === 'rename' ? 'A file exists at the original location; will be renamed' : item.state === 'changed' ? 'File changed' : 'File does not exist' }}
        </span>
      </button>
    </section>
    <footer class="action-bar"><button class="button secondary" @click="store.go('history')">← Back to history</button><span>Restoring never overwrites files already at the original location.</span><button class="button undo" :disabled="!selected.size || store.busy" @click="store.executeUndo([...selected])">↶ Restore {{ selected.size }} files</button></footer>
  </div>
</template>
