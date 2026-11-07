<script setup lang="ts">
import { useAppStore } from '../stores/app'
import CareVisual from '../components/CareVisual.vue'
import AppIcon from '../components/AppIcon.vue'

const store = useAppStore()
</script>

<template>
  <div class="page scan-page" aria-busy="true">
    <div class="scan-center">
    <CareVisual mode="scanning" />
    <span class="eyebrow">LOOKING CLOSER</span>
    <h1>{{ store.profile.presetType === 'duplicates' ? 'Finding duplicate files' : store.profile.presetType === 'similar-photos' ? 'Finding similar photos' : 'Scanning' }}</h1>
    <div class="scan-count"><strong>{{ store.scanChecked.toLocaleString() }}</strong><span>files checked</span></div>
    <div class="scan-current"><small>Checking</small><code :title="store.scanPath || store.scanLabel">{{ store.scanLabel || store.scanPath }}</code></div>
    <div v-if="store.profile.presetType === 'duplicates'" class="scan-stages"><span class="active">Filtering by size and comparing full contents</span></div>
    <div v-else-if="store.profile.presetType === 'similar-photos'" class="scan-stages"><span class="active">{{ store.scanLabel || 'Comparing exact duplicates and similar photos' }}</span></div>
    <p class="scan-safety"><AppIcon name="shield" :size="16" />Scanning only reads file info and changes no files.</p>
    </div>
    <footer class="action-bar"><button class="button secondary" @click="store.cancelScan">Cancel scan</button><span>Cancelling returns to plan settings and leaves no changes.</span></footer>
  </div>
</template>
