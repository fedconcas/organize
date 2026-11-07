<script setup lang="ts">
import { useAppStore } from '../stores/app'
import CareVisual from '../components/CareVisual.vue'

const store = useAppStore()
</script>

<template>
  <div class="page onboarding-page">
    <section class="onboarding-hero">
      <CareVisual />
      <h1>Tidy messy folders while keeping room to change your mind</h1>
      <p>Organize It scans first and gives an exact preview. Files move only after you confirm, and cleanup items go to quarantine.</p>
    </section>
    <section class="onboarding-grid">
      <article><span>1</span><h2>Choose a plan</h2><p>Start with four common plans: by type, by date, old installers and duplicate files.</p></article>
      <article><span>2</span><h2>See the full preview first</h2><p>Where each file goes from and to, whether names clash, and why it’s skipped are all explained before running.</p></article>
      <article><span>3</span><h2>Can be undone when needed</h2><p>History records every action; files can be safely restored if the destination files haven’t changed.</p></article>
    </section>
    <div class="onboarding-safe">✓ Never overwrites existing files  ✓ Never permanently deletes  ✓ Must confirm before running</div>
    <button class="button primary onboarding-start" @click="store.completeOnboarding">Get started Organize</button>
  </div>
</template>
