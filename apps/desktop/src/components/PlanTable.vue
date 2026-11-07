<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import type { PlanItem } from '../types'
import { formatBytes, fileName, folderName } from '../utils'

const props = defineProps<{ items: PlanItem[]; categories?: Array<{ id: string; name: string }> }>()
const emit = defineEmits<{ toggle: [itemId: string]; setCategory: [itemId: string, categoryId: string] }>()
const search = ref('')
const filter = ref<'all' | 'suggestions' | 'conflict' | 'skip' | 'excluded'>('all')
const CONFIDENCE_LABELS: Record<string, string> = { high: 'High', medium: 'Med', low: 'Low' }
const isSuggestion = (item: PlanItem) => ['content', 'analysis'].includes(String(item.metadata.source ?? ''))
const suggestionCount = computed(() => props.items.filter(isSuggestion).length)
const scrollTop = ref(0)
const scrollContainer = ref<HTMLDivElement>()
const viewportHeight = ref(0)
const rowHeight = 64
const headerHeight = 42
const detailItem = ref<PlanItem>()
const detailOpen = ref(false)
let resizeObserver: ResizeObserver | undefined

onMounted(() => {
  const container = scrollContainer.value
  if (!container) return
  const measure = () => { viewportHeight.value = Math.max(0, container.clientHeight - headerHeight) }
  resizeObserver = new ResizeObserver(measure)
  resizeObserver.observe(container)
  measure()
})
onBeforeUnmount(() => resizeObserver?.disconnect())

function resetScroll() {
  scrollTop.value = 0
  if (scrollContainer.value) scrollContainer.value.scrollTop = 0
}
watch([search, filter, () => props.items.length], resetScroll, { flush: 'post' })

const filtered = computed(() => props.items.filter((item) => {
  if (search.value && !`${item.sourcePath} ${item.targetPath ?? ''}`.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())) return false
  if (filter.value === 'suggestions') return isSuggestion(item)
  if (filter.value === 'conflict') return item.warningCode === 'TARGET_CONFLICT'
  if (filter.value === 'skip') return item.status === 'skipped'
  if (filter.value === 'excluded') return item.status !== 'skipped' && !item.selected
  return true
}))
const start = computed(() => Math.min(Math.max(0, filtered.value.length - 1), Math.max(0, Math.floor(scrollTop.value / rowHeight) - 4)))
const end = computed(() => Math.min(filtered.value.length, start.value + Math.ceil(viewportHeight.value / rowHeight) + 9))
const visible = computed(() => filtered.value.slice(start.value, end.value))

function operationLabel(item: PlanItem) {
  if (item.status === 'skipped') return 'Skip'
  const label = item.operation === 'quarantine' ? 'Quarantine' : 'Move'
  return item.warningCode === 'TARGET_CONFLICT' ? `${label} and rename` : label
}

function reasonLabel(item: PlanItem) {
  return item.reason || (item.warningCode === 'TARGET_CONFLICT' ? 'Name clash; a new name will be used' : '—')
}

function showDetails(item: PlanItem) {
  detailItem.value = item
  detailOpen.value = true
}
</script>

<template>
  <section class="plan-list">
    <div class="plan-tools">
      <label class="search-box">⌕<input v-model="search" aria-label="Search file names or paths" placeholder="Search file names or paths" /></label>
      <div class="segments">
        <button :class="{ active: filter === 'all' }" @click="filter = 'all'">All {{ items.length }}</button>
        <button v-if="suggestionCount" :class="{ active: filter === 'suggestions' }" @click="filter = 'suggestions'">Suggestions {{ suggestionCount }}</button>
        <button :class="{ active: filter === 'conflict' }" @click="filter = 'conflict'">Name clash</button>
        <button :class="{ active: filter === 'skip' }" @click="filter = 'skip'">Skip</button>
        <button :class="{ active: filter === 'excluded' }" @click="filter = 'excluded'">Excluded</button>
      </div>
    </div>
    <div ref="scrollContainer" class="virtual-scroll" role="region" aria-label="Organizing preview list; scrolls horizontally and vertically" tabindex="0" @scroll="scrollTop = ($event.target as HTMLElement).scrollTop">
      <div class="plan-table-content" role="table" aria-label="Organizing preview" :aria-rowcount="filtered.length + 1">
        <div class="table-head" role="row"><span role="columnheader">Select</span><span role="columnheader">File</span><span role="columnheader">Location change</span><span role="columnheader">Action</span><span role="columnheader">Size</span><span role="columnheader">Notes</span><span role="columnheader">Details</span></div>
        <div v-if="!filtered.length" class="plan-empty">{{ items.length ? 'No matching files. Adjust your search or filters.' : 'No files need organizing.' }}</div>
        <div :style="{ height: `${filtered.length * rowHeight}px`, position: 'relative' }">
        <div class="virtual-inner" :style="{ transform: `translateY(${start * rowHeight}px)` }">
          <div
            v-for="(item, index) in visible"
            :key="item.itemId"
            class="plan-row"
            :class="{ excluded: !item.selected && item.status !== 'skipped' }"
            role="row"
            :aria-rowindex="start + index + 2"
            @click="emit('toggle', item.itemId)"
          >
            <span role="cell"><input type="checkbox" class="plan-checkbox" :checked="item.selected" :disabled="item.status === 'skipped'" :aria-label="`Choose file ${fileName(item.sourcePath)}`" @click.stop @change="emit('toggle', item.itemId)" /></span>
            <span class="file-cell" role="cell"><b :title="fileName(item.sourcePath)">{{ fileName(item.sourcePath) }}</b><small :title="item.sourcePath">{{ item.sourcePath }}</small></span>
            <span class="destination-cell" role="cell" :title="item.targetPath ?? 'Left in place'"><span class="path-change"><em :title="item.sourcePath">{{ folderName(item.sourcePath) }}</em><i>→</i><em v-if="item.targetPath" class="target">{{ folderName(item.targetPath) }}</em><em v-else>Left in place</em></span><small v-if="item.targetPath" :title="fileName(item.targetPath)">{{ fileName(item.targetPath) }}</small></span>
            <span role="cell"><span class="op-badge" :class="item.warningCode ? 'warn' : item.operation">{{ operationLabel(item) }}</span></span>
            <span class="number" role="cell">{{ formatBytes(item.size) }}</span>
            <span v-if="categories && item.status !== 'skipped' && item.metadata.category" class="category-cell" role="cell" @click.stop>
              <span class="category-line"><span class="category-chip" :title="String(item.metadata.categoryName ?? '')">{{ item.metadata.categoryName }}</span><span v-if="isSuggestion(item) || item.metadata.source === 'manual'" class="confidence-badge" :class="String(item.metadata.confidence)">{{ item.metadata.source === 'manual' ? 'Yours' : CONFIDENCE_LABELS[String(item.metadata.confidence)] }}</span></span>
              <span class="category-line">
                <select class="category-select" :value="String(item.metadata.category)" :aria-label="`Category for ${fileName(item.sourcePath)}`" @change="emit('setCategory', item.itemId, ($event.target as HTMLSelectElement).value)">
                  <option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option>
                </select>
                <button v-if="isSuggestion(item) && !item.selected" class="text-button" @click="emit('toggle', item.itemId)">Accept</button>
              </span>
            </span>
            <span v-else class="reason" role="cell" :title="reasonLabel(item)">{{ reasonLabel(item) }}</span>
            <span role="cell"><button class="text-button" :aria-label="`View file details ${fileName(item.sourcePath)}`" @click.stop="showDetails(item)">Details</button></span>
          </div>
        </div>
        </div>
      </div>
    </div>
    <div class="plan-list-footer">Showing {{ filtered.length }} / {{ items.length }} files · Click “Details” to see long file names, full paths and explanations</div>
  </section>
  <NModal v-model:show="detailOpen">
    <section v-if="detailItem" class="dialog plan-detail" role="dialog" aria-modal="true" aria-labelledby="plan-detail-title">
      <h2 id="plan-detail-title">File details</h2>
      <dl>
        <dt>File name</dt><dd>{{ fileName(detailItem.sourcePath) }}</dd>
        <dt>Original path</dt><dd>{{ detailItem.sourcePath }}</dd>
        <dt>Target path</dt><dd>{{ detailItem.targetPath ?? 'Left in place' }}</dd>
        <dt>Action</dt><dd>{{ operationLabel(detailItem) }}</dd>
        <dt>Size</dt><dd>{{ formatBytes(detailItem.size) }} ({{ detailItem.size.toLocaleString() }} bytes)</dd>
        <dt>Notes</dt><dd>{{ reasonLabel(detailItem) }}</dd>
        <template v-if="detailItem.metadata.categoryName"><dt>Category</dt><dd>{{ detailItem.metadata.categoryName }}{{ detailItem.metadata.confidence ? ` · ${CONFIDENCE_LABELS[String(detailItem.metadata.confidence)] ?? ''} confidence` : '' }}</dd></template>
      </dl>
      <div><button class="button secondary" @click="detailOpen = false">Close</button></div>
    </section>
  </NModal>
</template>
