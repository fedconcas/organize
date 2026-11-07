<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '../stores/app'
import { pickDirectories } from '../api'
import { draftIssues } from '../proposal'
import { formatBytes } from '../utils'
import AppIcon from '../components/AppIcon.vue'
import CategoryProposalEditor from '../components/CategoryProposalEditor.vue'
import SwitchToggle from '../components/SwitchToggle.vue'

const store = useAppStore()
const baseName = (path: string) => path.replace(/\/+$/, '').split('/').at(-1) || path
const running = computed(() => store.analysisStage !== 'idle')
const summary = computed(() => store.inventory)
const families = computed(() => Object.entries(summary.value?.families ?? {}).filter(([, count]) => count > 0))
const FAMILY_LABELS: Record<string, string> = { documents: 'Documents', images: 'Images', videos: 'Videos', audio: 'Audio', archives: 'Archives', installers: 'Installers', other: 'Other' }
const STAGES = [
  { id: 'reading', label: 'Reading' },
  { id: 'embedding', label: 'Comparing' },
  { id: 'grouping', label: 'Grouping' },
  { id: 'naming', label: 'Naming' },
] as const
const stageIndex = computed(() => STAGES.findIndex((stage) => stage.id === store.analysisStage))
const NOTICES: Record<string, string> = {
  AI_DISABLED: 'Local AI is off, so this is a simple proposal by file type and photo details. Turn on “Local AI” in Settings to group files by content.',
  AI_UNAVAILABLE: 'AI unavailable, simple proposal. Install Ollama and the models chosen in Settings (for example “ollama pull nomic-embed-text” and “ollama pull qwen2.5:3b-instruct” in Terminal); Organize never downloads anything itself.',
  NAMING_FALLBACK: 'The local model took too long to name some groups, so they got simple names. Rename them as you like.',
}
const notice = computed(() => (store.proposal?.notice ? NOTICES[store.proposal.notice] : ''))
const blocked = computed(() => !store.draft || draftIssues(store.draft, store.proposal?.maxCategories ?? 12).length > 0)
const tooFew = computed(() => Boolean(store.proposal?.tooFew) || (summary.value && summary.value.files < 10))

async function addSource() {
  for (const value of await pickDirectories(true)) if (!store.profile.sourceFolders.includes(value)) store.profile.sourceFolders.push(value)
  store.resetAnalysis()
}
function removeSource(index: number) {
  store.profile.sourceFolders.splice(index, 1)
  store.resetAnalysis()
}
function back() {
  store.resetAnalysis()
  store.go('home')
}
function startOver() {
  store.proposal = undefined
  store.draft = undefined
}
</script>

<template>
  <div class="page scroll-page analyze-page">
    <header class="page-header">
      <div>
        <span class="config-kicker"><AppIcon name="sparkle" :size="14" />Sort by type</span>
        <h1>{{ store.draft ? 'Review the proposed categories' : 'Look at your folders first' }}</h1>
        <p>{{ store.draft ? 'Rename, merge, split or remove categories. Nothing moves until you confirm the preview.' : 'Organize reads file names, types and photo details on this Mac to suggest categories. No files change.' }}</p>
      </div>
    </header>

    <section v-if="!store.draft" class="panel config-section analyze-sources">
      <header class="section-head">
        <div class="section-title"><h2>Folders</h2><p>Reading only lists files and looks inside a few of them</p></div>
        <div class="section-actions"><button class="button secondary small" :disabled="running" @click="addSource"><AppIcon name="plus" :size="15" />Add folder</button></div>
      </header>
      <div class="route">
        <div v-for="(source, index) in store.profile.sourceFolders" :key="`${source}-${index}`" class="path-row">
          <span class="path-icon"><AppIcon name="folder" :size="17" /></span>
          <span class="path-text"><b>{{ baseName(source) }}</b><code :title="source">{{ source }}</code></span>
          <span class="path-actions"><button class="icon-button danger" title="Remove" :aria-label="`Remove folder ${baseName(source)}`" :disabled="running" @click="removeSource(index)"><AppIcon name="close" :size="15" /></button></span>
        </div>
        <div class="route-option">
          <span><b>Include files in subfolders</b><small>{{ store.profile.includeSubfolders ? 'Looks through all subfolders' : 'Only the first level of the chosen folders' }}</small></span>
          <SwitchToggle v-model="store.profile.includeSubfolders" label="Include files in subfolders" @update:model-value="store.resetAnalysis()" />
        </div>
      </div>
    </section>

    <section v-if="summary && !store.draft" class="panel analyze-summary" aria-live="polite">
      <div class="summary-numbers">
        <div><strong>{{ summary.files.toLocaleString() }}</strong><span>files</span></div>
        <div><strong>{{ formatBytes(summary.bytes) }}</strong><span>in total</span></div>
        <div><strong>{{ summary.photos }}</strong><span>camera photos</span></div>
        <div><strong>{{ summary.screenshots }}</strong><span>screenshots</span></div>
      </div>
      <div class="family-chips">
        <span v-for="[family, count] in families" :key="family" class="ext-chip">{{ FAMILY_LABELS[family] ?? family }} {{ count }}</span>
        <span v-for="item in summary.topExtensions" :key="item.extension" class="ext-chip mini">.{{ item.extension }} {{ item.count }}</span>
      </div>
      <p v-if="summary.withLocation" class="hint"><AppIcon name="lock" :size="13" />{{ summary.withLocation }} photos have a location. It is used on this Mac to group trips and is never stored.</p>
    </section>

    <div v-if="tooFew && !running" class="banner warn inset">Too few files to group, use standard categories.</div>
    <div v-if="notice && store.draft" class="banner undo inset" role="status">{{ notice }}</div>
    <div v-if="!store.settings.aiEnabled && summary && !store.draft && !running" class="banner quarantine inset">Local AI is off. You can still get a simple proposal, or turn on “Local AI” in Settings.</div>

    <section v-if="running" class="panel analyze-progress" aria-busy="true">
      <ol class="stage-list">
        <li v-for="(stage, index) in STAGES" :key="stage.id" :class="{ done: index < stageIndex, current: index === stageIndex }">{{ stage.label }}</li>
      </ol>
      <p>{{ store.analysisStage === 'naming' ? `Naming ${store.analysisDone} / ${store.analysisTotal || store.analysisDone}` : store.analysisTotal ? `${store.analysisDone} / ${store.analysisTotal}` : `${store.analysisDone.toLocaleString()} files` }}</p>
      <button class="button secondary" @click="store.cancelAnalysis">Cancel</button>
      <small>Cancelling keeps nothing from this analysis.</small>
    </section>

    <CategoryProposalEditor v-if="store.draft && !running" />

    <footer class="action-bar">
      <button v-if="!store.draft" class="button secondary" :disabled="running" @click="back">← Back to home</button>
      <button v-else class="button secondary" :disabled="running" @click="startOver">← Back to summary</button>
      <template v-if="!store.draft">
        <span />
        <button v-if="!summary" class="button primary" :disabled="running || !store.profile.sourceFolders.length" @click="store.scanFolders()">Read folders<AppIcon name="arrow" :size="16" /></button>
        <template v-else>
          <button class="button secondary" :disabled="running" @click="store.go('config')">Define my own</button>
          <button class="button secondary" :disabled="running" @click="store.useStandardCategories()">Use standard type categories</button>
          <button class="button primary" :disabled="running || Boolean(tooFew)" @click="store.proposeCategories(store.settings.aiEnabled ? 'ai' : 'heuristic')">{{ store.settings.aiEnabled ? 'Propose categories with AI' : 'Propose simple categories' }}<AppIcon name="sparkle" :size="16" /></button>
        </template>
      </template>
      <template v-else>
        <span>{{ store.draft.categories.length }} categories, {{ store.draft.other.count }} files to Other / Unsorted</span>
        <button class="button primary" :disabled="blocked || store.busy" @click="store.acceptCategories()">Accept categories<AppIcon name="arrow" :size="16" /></button>
      </template>
    </footer>
  </div>
</template>
