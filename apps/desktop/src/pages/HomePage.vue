<script setup lang="ts">
import { useAppStore } from '../stores/app'
import AppIcon from '../components/AppIcon.vue'
import CareVisual from '../components/CareVisual.vue'
import type { PresetType } from '../types'
import { formatDate } from '../utils'

const store = useAppStore()
const today = new Date()
const flowFor = (id: PresetType) => id === 'by-type' && store.settings.aiEnabled ? ['Choose folders', 'Local AI proposes categories'] : presentation[id].flow
const presentation: Record<PresetType, { icon: string; title: string; safety: string; tone: string; flow: string[] }> = {
  'by-type': { icon: 'folder', title: 'Messy files, neatly sorted', safety: 'Moves only, never deletes', tone: 'mint', flow: ['Choose folders', 'Custom categories'] },
  'by-date': { icon: 'image', title: 'Give every photo its place', safety: 'Archive by date taken', tone: 'blue', flow: ['Photos and screenshots', `${today.getFullYear()} / ${today.getMonth() + 1}`] },
  'old-installers': { icon: 'archive', title: 'Make room from old installers', safety: 'Move to quarantine; restorable', tone: 'peach', flow: ['Over 90 days', 'Safe quarantine'] },
  duplicates: { icon: 'duplicate', title: 'Identical files, keep only one', safety: 'You choose what to keep', tone: 'pink', flow: ['Comparing file contents', 'Choose group by group'] },
}
</script>

<template>
  <div class="page scroll-page home-page">
    <header class="home-heading"><div><span class="eyebrow">YOUR SPACE, ORGANIZED</span><h1>Smart Organize</h1></div><span class="local-pill"><AppIcon name="lock" :size="14" />All file processing happens on this Mac</span></header>
    <section class="home-hero">
      <div class="hero-copy"><span class="hero-kicker"><AppIcon name="sparkle" :size="16" />Less clutter, more ease</span><h2>Put files where they belong.</h2><p>Start with one folder. See where every file goes first, <br>Then leave the organizing to Organize with peace of mind.</p><button class="button primary hero-action" :disabled="!store.engineReady" @click="store.choosePreset('by-type')">Start organizing<AppIcon name="arrow" :size="18" /></button><small>Choose folders, then scan · No files change until you confirm</small></div>
      <CareVisual />
    </section>
    <div class="home-section-heading"><h2>Choose a way to organize your files</h2><span>{{ store.presets.length }} tools, all safety-first</span></div>
    <div class="home-grid">
      <div>
        <div class="preset-grid">
          <button
            v-for="preset in store.presets"
            :key="preset.id"
            class="preset-card"
            :class="presentation[preset.id].tone"
            :disabled="!store.engineReady"
            @click="store.choosePreset(preset.id)"
          >
            <div class="preset-top">
              <span class="preset-icon"><AppIcon :name="presentation[preset.id].icon" :size="30" /></span>
              <div><small>{{ preset.name }}</small><h2>{{ presentation[preset.id].title }}</h2><p>{{ preset.description }}</p></div>
            </div>
            <div class="flow-preview">
              <template v-for="(segment, index) in flowFor(preset.id)" :key="`${segment}-${index}`">
                <span>{{ segment }}</span><i v-if="index < flowFor(preset.id).length - 1">→</i>
              </template>
            </div>
            <div class="preset-footer"><span class="safety-chip"><AppIcon name="check" :size="13" />{{ presentation[preset.id].safety }}</span><span class="preset-open"><AppIcon name="arrow" :size="18" /></span></div>
          </button>
        </div>
        <h3 v-if="store.history.length" class="section-title">Recent tasks</h3>
        <section v-if="store.history.length" class="panel recent-list">
          <button v-for="run in store.history.slice(0, 3)" :key="run.run_id" @click="store.go('history')">
            <span class="status-dot" :class="run.status" />
            <span><b>{{ run.profile.name }}</b><small>{{ formatDate(run.started_at) }}, {{ run.success }} completed</small></span>
            <span class="op-badge" :class="run.status === 'completed' ? 'ok' : 'warn'">{{ run.status === 'completed' ? 'Done' : 'Partly succeeded' }}</span>
          </button>
        </section>
      </div>
      <aside class="home-aside">
        <section v-if="store.history[0]" class="panel last-run">
          <div class="panel-title">↶ Last run <small>{{ formatDate(store.history[0].started_at) }}</small></div>
          <div class="panel-body"><p>{{ store.history[0].profile.name }}</p><strong>{{ store.history[0].success }}</strong> files processed</div>
          <button class="button undo" :disabled="!store.history[0].undoable_count" @click="store.prepareUndo(store.history[0].run_id)">↶ Undo last run</button>
        </section>
        <section v-if="store.lastProfile" class="panel continue-card">
          <div class="panel-title">Continue last plan</div>
          <div class="panel-body"><p>{{ store.lastProfile.name }}</p><small>{{ store.lastProfile.sourceFolders.join(', ') }} → {{ store.lastProfile.targetFolder }}</small></div>
          <button class="button secondary" @click="store.useProfile(store.lastProfile)">Rescan with this plan</button>
        </section>
      </aside>
    </div>
    <div class="home-trust"><span><AppIcon name="shield" :size="15" />Doesn’t overwrite existing files</span><span><AppIcon name="history" :size="15" />Keep action history</span><span><AppIcon name="lock" :size="15" />No need to upload files</span></div>
  </div>
</template>
