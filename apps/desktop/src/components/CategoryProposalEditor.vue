<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { canMerge, confidenceSpread, draftIssues, merge, moveExample, OTHER, remove, rename } from '../proposal'
import AppIcon from './AppIcon.vue'

const store = useAppStore()
const selected = ref<string[]>([])
const dragging = ref<{ index: number; from: string }>()
const dropTarget = ref<string>()
const draft = computed(() => store.draft!)
const issues = computed(() => draftIssues(draft.value, store.proposal?.maxCategories ?? 12))
const mergeable = computed(() => canMerge(draft.value, selected.value))
const KIND_LABELS = { content: 'By content (AI)', metadata: 'By photo details', extension: 'By file type' } as const
const LEVEL_LABELS = { high: 'High', medium: 'Med', low: 'Low' } as const

function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}
function onName(id: string, value: string) { store.draft = rename(draft.value, id, value) }
function onFolder(id: string, value: string) {
  const category = draft.value.categories.find((item) => item.id === id)
  if (category) store.draft = rename(draft.value, id, category.name, value)
}
function doMerge() { store.draft = merge(draft.value, selected.value); selected.value = [] }
function doRemove(id: string) { store.draft = remove(draft.value, id); selected.value = selected.value.filter((item) => item !== id) }
function onDragStart(index: number, from: string) { dragging.value = { index, from } }
function onDrop(to: string) {
  if (dragging.value) store.draft = moveExample(draft.value, dragging.value.index, dragging.value.from, to)
  dragging.value = undefined
  dropTarget.value = undefined
}
function issuesFor(id: string) { return issues.value.filter((issue) => issue.id === id) }
</script>

<template>
  <section class="proposal-editor">
    <div class="proposal-tools">
      <span>{{ draft.categories.length }} categories · drag an example onto another category to move it</span>
      <button class="button secondary small" :disabled="!mergeable" :title="selected.length >= 2 && !mergeable ? 'Only categories of the same kind can be merged' : ''" @click="doMerge"><AppIcon name="layers" :size="14" />Merge selected ({{ selected.length }})</button>
    </div>
    <div class="proposal-grid">
      <article
        v-for="category in draft.categories"
        :key="category.id"
        class="panel proposal-card"
        :class="{ chosen: selected.includes(category.id), drop: dropTarget === category.id, invalid: issuesFor(category.id).length }"
        @dragover.prevent="dropTarget = category.id"
        @dragleave="dropTarget = undefined"
        @drop.prevent="onDrop(category.id)"
      >
        <header>
          <input type="checkbox" class="plan-checkbox" :checked="selected.includes(category.id)" :aria-label="`Select ${category.name} for merging`" @change="toggle(category.id)" />
          <span class="kind-badge" :class="category.kind">{{ KIND_LABELS[category.kind] }}</span>
          <strong>{{ category.count }} files</strong>
        </header>
        <label class="field"><span>Name</span><input :value="category.name" maxlength="24" @input="onName(category.id, ($event.target as HTMLInputElement).value)" /></label>
        <label class="field"><span>Folder</span><input :value="category.folderName" maxlength="32" @input="onFolder(category.id, ($event.target as HTMLInputElement).value)" /></label>
        <small v-for="issue in issuesFor(category.id)" :key="issue.message" class="issue">{{ issue.message }}</small>
        <p v-if="category.description" class="proposal-description">{{ category.description }}</p>
        <div class="confidence-bar" :title="`High ${category.confidence.high} · Medium ${category.confidence.medium} · Low ${category.confidence.low}`">
          <i v-for="part in confidenceSpread(category)" :key="part.level" :class="part.level" :style="{ flex: part.share }" />
        </div>
        <div class="confidence-legend"><span v-for="(label, level) in LEVEL_LABELS" :key="level">{{ label }} {{ category.confidence[level] }}</span></div>
        <ul class="examples">
          <li v-for="example in category.examples" :key="example.index" draggable="true" :title="example.name" @dragstart="onDragStart(example.index, category.id)">{{ example.name }}</li>
          <li v-if="!category.examples.length" class="muted">No examples</li>
        </ul>
        <footer>
          <button v-if="category.splittable" class="text-button" :disabled="store.busy" @click="store.splitCategory(category.sources[0])">Split in two</button>
          <button class="text-button danger" @click="doRemove(category.id)"><AppIcon name="trash" :size="13" />Remove</button>
        </footer>
      </article>
      <article class="panel proposal-card other" :class="{ drop: dropTarget === OTHER }" @dragover.prevent="dropTarget = OTHER" @dragleave="dropTarget = undefined" @drop.prevent="onDrop(OTHER)">
        <header><span class="kind-badge">Other / Unsorted</span><strong>{{ draft.other.count }} files</strong></header>
        <p class="proposal-description">Files that don’t fit any category go to “{{ store.profile.parameters.otherFolder || 'Other files' }}”.</p>
        <ul class="examples">
          <li v-for="example in draft.other.examples" :key="example.index" draggable="true" :title="example.name" @dragstart="onDragStart(example.index, OTHER)">{{ example.name }}</li>
        </ul>
      </article>
    </div>
    <p v-for="issue in issues.filter((item) => !item.id)" :key="issue.message" class="banner warn inset">{{ issue.message }}</p>
  </section>
</template>
