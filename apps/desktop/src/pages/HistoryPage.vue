<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAppStore } from '../stores/app'
import { formatDate } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import AppIcon from '../components/AppIcon.vue'

const store = useAppStore()
const activeId = ref<string>()
const filter = ref('all')
const operationFilter = ref('applied')
const runs = computed(() => store.history.filter(run => filter.value === 'all' ||
  (filter.value === 'undo' ? run.undoable_count > 0 : run.status === filter.value)))
const active = computed(() => runs.value.find((run) => run.run_id === activeId.value) ?? runs.value[0])
const labels: Record<string, string> = { completed: 'Done', partial: 'Partly succeeded', failed: 'Failed', cancelled: 'Stopped', running: 'Running', applied: 'Completed', undone: 'Undone', skipped: 'Skipped', started: 'Incomplete' }
const operations = computed(() => store.historyDetail?.run_id === active.value?.run_id ? store.historyDetail.operations.filter(op => operationFilter.value === 'applied' ? ['applied','undone'].includes(op.state) : op.state === operationFilter.value) : [])
watch(() => active.value?.run_id, (runId) => { if (runId) void store.loadHistoryDetail(runId) }, { immediate: true })
</script>

<template>
  <div class="page scroll-page">
    <PageHeader title="History" description="Every run records where each file went. Runs that can be undone are marked.">
      <div class="segments"><button v-for="[id,label] in [['all','All'],['undo','Undo can be attempted'],['partial','Partly succeeded'],['failed','Failed'],['cancelled','Stopped']]" :key="id" :class="{ active: filter === id }" @click="filter = id">{{ label }}</button></div>
    </PageHeader>
    <div v-if="!runs.length" class="empty-state"><span><AppIcon name="history" :size="48" /></span><h2>{{ store.history.length ? 'No records match the filter' : 'No organizing records yet' }}</h2><p>After organizing, where each file went is recorded here.</p><button class="button primary" @click="store.go('home')">Go to Home and choose a plan</button></div>
    <div v-else class="history-grid">
      <div class="history-list">
        <button v-for="run in runs" :key="run.run_id" :class="{ active: active?.run_id === run.run_id }" @click="activeId = run.run_id">
          <span class="history-icon"><AppIcon name="folder" /></span><span><b>{{ run.profile.name }}</b><small>{{ formatDate(run.started_at) }}, source: {{ run.profile.sourceFolders[0] }}</small><em><i class="op-badge" :class="run.status === 'completed' ? 'ok' : 'warn'">{{ labels[run.status] }}</i><i v-if="run.undoable_count" class="op-badge undo">Undo can be attempted</i></em></span><strong>{{ run.total }} files</strong>
        </button>
      </div>
      <section v-if="active" class="panel history-detail">
        <div class="panel-title"><span>{{ active.profile.name }}</span><span class="op-badge" :class="active.status === 'completed' ? 'ok' : 'warn'">{{ labels[active.status] }}</span></div>
        <div class="profile-snapshot"><small>Plan snapshot · settings at that time</small><dl><dt>Source</dt><dd>{{ active.profile.sourceFolders.join(', ') }}</dd><dt>Organize into</dt><dd>{{ active.profile.targetFolder }}</dd><dt>Result</dt><dd>{{ active.success }} succeeded, {{ active.skipped }} skipped, {{ active.failed }} Failed</dd></dl></div>
        <div class="detail-tabs"><button v-for="[id,label] in [['applied','Processed'],['skipped','Skip'],['failed','Failed']]" :key="id" :class="{ active: operationFilter === id }" @click="operationFilter = id">{{ label }}</button></div>
        <div class="history-operations">
          <div v-if="!operations.length" class="history-placeholder">No file actions are recorded for this category.</div>
          <div v-for="operation in operations" :key="operation.operation_id" class="history-operation">
            <span class="op-badge" :class="operation.operation === 'quarantine' ? 'quarantine' : 'move'">{{ operation.operation === 'quarantine' ? 'Quarantine' : 'Move' }}</span>
            <span><b>{{ operation.source_path.split('/').at(-1) }}</b><small>{{ operation.source_path }} → {{ operation.target_path }}</small><small v-if="operation.error_code">{{ operation.error_code }} {{ operation.error_detail }}</small></span>
            <span class="op-badge" :class="operation.state === 'applied' ? 'ok' : operation.state === 'undone' ? 'undo' : 'fail'">{{ labels[operation.state] }}</span>
          </div>
        </div>
        <footer><span>Files are checked for restorability before undoing</span><button class="button undo" :disabled="store.busy || !active.undoable_count" @click="store.prepareUndo(active.run_id)">↶ Undo this run</button></footer>
      </section>
    </div>
  </div>
</template>
