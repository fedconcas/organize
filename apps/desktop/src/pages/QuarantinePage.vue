<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { fileName, formatBytes, formatDate } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import AppIcon from '../components/AppIcon.vue'
import { pickDirectories } from '../api'

const store = useAppStore()
const selected = ref(new Set<string>())
const selectedSize = computed(() => store.quarantine.filter((item) => selected.value.has(item.quarantine_id)).reduce((sum, item) => sum + item.size, 0))
const expired = computed(() => store.quarantine.filter(item => Date.parse(item.retention_until) <= Date.now()).length)
function toggle(id: string) { const next = new Set(selected.value); next.has(id) ? next.delete(id) : next.add(id); selected.value = next }
async function restore(original = true) {
  const ids = [...selected.value]
  let destination: string | undefined
  if (!original) [destination] = await pickDirectories(false)
  if (!original && !destination) return
  if (await store.restoreQuarantine(ids, destination)) selected.value = new Set([...selected.value].filter(id => store.quarantine.some(item => item.quarantine_id === id)))
}
async function moveToTrash() {
  if (!window.confirm(`Move the selected ${selected.value.size} files to the system Trash?`)) return
  if (await store.trashQuarantine([...selected.value])) selected.value = new Set([...selected.value].filter(id => store.quarantine.some(item => item.quarantine_id === id)))
}
</script>

<template>
  <div class="page scroll-page quarantine-page">
    <PageHeader title="Quarantine" description="Files here have not been deleted. You can put them back, or move them to the system Trash once you’re sure you don’t need them." />
    <section class="quarantine-summary"><div><strong>{{ store.quarantine.length }}</strong><span>files</span></div><div><strong>{{ formatBytes(store.quarantine.reduce((n, item) => n + item.size, 0)) }}</strong><span>Space used</span></div><div><strong>{{ expired }}</strong><span>Reminder time has passed</span></div><code>{{ store.settings.quarantineFolder }}(existing files may be in the old location)</code></section>
    <div v-if="!store.quarantine.length" class="empty-state"><span><AppIcon name="shield" :size="48" /></span><h2>Quarantine is empty</h2><p>Old installers and duplicate files put files here, and you can restore them at any time.</p></div>
    <section v-else class="panel quarantine-table">
      <div class="q-head"><span>Select</span><span>File</span><span>Original location</span><span>Why it’s here</span><span>Quarantined at</span><span>Size</span></div>
      <button v-for="item in store.quarantine" :key="item.quarantine_id" @click="toggle(item.quarantine_id)"><span class="check" :class="{ on: selected.has(item.quarantine_id) }">{{ selected.has(item.quarantine_id) ? '✓' : '' }}</span><span><b>{{ fileName(item.original_path) }}</b><small>{{ item.quarantine_path }}</small></span><code>{{ item.original_path }}</code><span>{{ item.reason }}</span><span>{{ formatDate(item.quarantined_at) }}</span><strong>{{ formatBytes(item.size) }}</strong></button>
    </section>
    <footer v-if="selected.size" class="action-bar"><span>Selected {{ selected.size }} files, {{ formatBytes(selectedSize) }}</span><button class="button danger" :disabled="store.busy" @click="moveToTrash">Move to system Trash</button><button class="button secondary" :disabled="store.busy" @click="restore(false)">Restore to another location</button><button class="button primary" :disabled="store.busy" @click="restore(true)">Restore to original location</button></footer>
  </div>
</template>
