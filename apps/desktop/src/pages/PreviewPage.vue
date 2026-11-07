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
    <PlanTable :items="store.plan.items" @toggle="store.toggleItem" />
    <footer class="action-bar"><button class="button secondary" @click="store.go('config')">← Back to edit plan</button><span>Selected <b>{{ selected }}</b> files, {{ formatBytes(store.selectedBytes) }}. No files are deleted or overwritten.</span><button class="button primary" :disabled="!selected" @click="confirming = true">Organize {{ selected }} files</button></footer>
    <div v-if="confirming" class="modal-backdrop" @click.self="confirming = false">
      <section class="dialog"><h2>Organize {{ selected }} files?</h2><p>These files will be moved to “{{ store.profile.targetFolder }}”. Files with the same name are renamed automatically and nothing is overwritten. You can undo after it finishes.</p><div><button class="button secondary" @click="confirming = false">Look again</button><button class="button primary" @click="confirming = false; store.executePlan()">Start organizing</button></div></section>
    </div>
  </div>
</template>
