<script setup lang="ts">
import { useAppStore } from '../stores/app'
import type { ViewName } from '../types'
import AppIcon from './AppIcon.vue'
import appIcon from '../assets/app-icon.png'
import type { PresetType } from '../types'
import { computed } from 'vue'

const store = useAppStore()
const items: Array<{ view: ViewName; icon: string; label: string }> = [
  { view: 'history', icon: 'history', label: 'History' },
  { view: 'quarantine', icon: 'shield', label: 'Quarantine' },
]
const modules: Array<{ id: PresetType; icon: string; label: string; tone: string }> = [
  { id: 'by-type', icon: 'folder', label: 'Sort by type', tone: 'mint' },
  { id: 'by-date', icon: 'image', label: 'Photo archive', tone: 'blue' },
  { id: 'old-installers', icon: 'archive', label: 'Old installers', tone: 'peach' },
  { id: 'duplicates', icon: 'duplicate', label: 'Duplicate files', tone: 'pink' },
]
const locked = computed(() => store.view === 'executing' || store.view === 'scan')
const inFlow = computed(() => ['config', 'scan', 'preview', 'duplicates', 'executing', 'result'].includes(store.view))

function navigate(view: ViewName) {
  if (locked.value) return
  store.go(view)
  if (view === 'history' || view === 'quarantine') void store.refreshCollections()
}
</script>

<template>
  <aside class="sidebar" :class="{ locked }">
    <div class="sidebar-brand"><span class="brand-icon"><img :src="appIcon" alt="" /></span><div><strong>Organize</strong><small>Put files where they belong</small></div></div>
    <nav>
      <button class="nav-item smart-nav" :class="{ active: store.view === 'home' }" :disabled="locked" @click="navigate('home')"><span class="nav-icon mint"><AppIcon name="sparkle" /></span><span>Smart Organize</span></button>
      <div class="nav-section-label">Organizing tool</div>
      <button v-for="module in modules" :key="module.id" class="nav-item" :class="{ active: inFlow && store.profile.presetType === module.id }" :disabled="locked" @click="store.choosePreset(module.id)"><span class="nav-icon" :class="module.tone"><AppIcon :name="module.icon" /></span><span>{{ module.label }}</span></button>
      <div class="nav-section-label">Library</div>
      <button
        v-for="item in items"
        :key="item.view"
        class="nav-item"
        :class="{ active: store.view === item.view }"
        :disabled="locked"
        @click="navigate(item.view)"
      >
        <span class="nav-icon muted"><AppIcon :name="item.icon" /></span>
        <span>{{ item.label }}</span>
        <span v-if="item.view === 'quarantine' && store.quarantine.length" class="nav-count">{{ store.quarantine.length }}</span>
      </button>
    </nav>
    <section class="guard-card">
      <h3><AppIcon name="shield" :size="16" />Organize with confidence</h3>
      <p>Preview first, then organize. Every step is traceable.</p>
      <button :disabled="locked" @click="navigate('history')"><span>Organizing records</span><strong>{{ store.history.length }} times</strong></button>
      <button :disabled="locked" @click="navigate('quarantine')"><span>Quarantined files</span><strong>{{ store.quarantine.length }} items</strong></button>
      <div><span>Delete permanently</span><strong>Never</strong></div>
    </section>
    <div class="sidebar-bottom"><button :disabled="locked" aria-label="Settings" @click="navigate('settings')"><AppIcon name="settings" :size="18" />Settings</button><button :disabled="locked" aria-label="About" @click="navigate('about')"><AppIcon name="info" :size="18" /></button></div>
  </aside>
</template>
