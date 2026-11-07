<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { api, pickDirectories, requestNotificationPermission } from '../api'
import type { ClassifierStatus, Settings } from '../types'
import PageHeader from '../components/PageHeader.vue'

const store = useAppStore()
const saving = ref(false)
const draft = ref({ ...store.settings })
async function save(values: Partial<Settings>) {
  saving.value = true
  try {
    if (values.notifyOnComplete && !await requestNotificationPermission()) {
      store.notice = 'Notifications aren’t allowed. Please authorize Organize in System Settings.'
      values.notifyOnComplete = false
    }
    await store.updateSettings(values)
  } catch (caught) { store.report(caught) } finally {
    draft.value = { ...store.settings }
    saving.value = false
  }
}
const status = ref<ClassifierStatus>()
const checking = ref(false)
const confirmClear = ref(false)
const models = computed(() => {
  const found = status.value?.models ?? []
  const withCurrent = (current: string) => [...new Set([current, ...found])]
  return { embed: withCurrent(store.settings.aiEmbedModel), llm: withCurrent(store.settings.aiLlmModel) }
})
async function checkModels() {
  checking.value = true
  try { status.value = await api.request<ClassifierStatus>('classifier.status', { probe: true }) }
  catch (caught) { store.report(caught) } finally { checking.value = false }
}
async function clearAiData() {
  confirmClear.value = false
  try {
    await api.request('ai.clearData')
    store.notice = 'Local AI data was cleared. Categories already in your plans stay, but content categories need a new proposal to match files.'
  } catch (caught) { store.report(caught) }
}
async function folder(key: 'defaultTargetFolder' | 'quarantineFolder') {
  try { const [path] = await pickDirectories(false); if (path) await save({ [key]: path }) }
  catch (caught) { store.report(caught) }
}
</script>

<template>
  <div class="page scroll-page narrow-page">
    <PageHeader title="Settings" :description="saving ? 'Saving…' : 'Changes are saved immediately.'" />
    <fieldset :disabled="saving" class="settings-fields">
      <section class="settings-group"><h2>Organize</h2><div><span><b>Organize into by default</b><small>{{ store.settings.defaultTargetFolder }}</small></span><button class="button secondary" @click="folder('defaultTargetFolder')">Change</button></div><label><span><b>Notify me when organizing finishes</b><small>Alerts when the window isn’t in front; requires system notification permission</small></span><input v-model="draft.notifyOnComplete" type="checkbox" @change="save({ notifyOnComplete: draft.notifyOnComplete })" /></label></section>
      <section class="settings-group"><h2>Safe</h2><div><span><b>Quarantine location</b><small>{{ store.settings.quarantineFolder }}</small><small>Only affects new scans; existing quarantined files are not moved. Rescan after changing.</small></span><button class="button secondary" @click="folder('quarantineFolder')">Change</button></div><label><span><b>Reminder time for newly quarantined files</b><small>The app never deletes automatically; reminder dates for existing files don’t change</small></span><input v-model.number="draft.retentionDays" class="number-input" type="number" min="7" max="3650" @change="save({ retentionDays: draft.retentionDays })" /> days</label><label><span><b>History items shown</b><small>Earlier records are kept; logs needed for undo are not deleted</small></span><input v-model.number="draft.historyLimit" class="number-input" type="number" min="10" max="2000" @change="save({ historyLimit: draft.historyLimit })" /> times</label></section>
      <section class="settings-group"><h2>Privacy</h2><label><span><b>Hide full paths when exporting diagnostics</b><small>Only affects exported files; local history keeps paths so undo works</small></span><input v-model="draft.redactPaths" type="checkbox" @change="save({ redactPaths: draft.redactPaths })" /></label></section>
      <section class="settings-group local-ai">
        <h2>Local AI</h2>
        <label><span><b>Propose categories from my files</b><small>Uses Ollama on this Mac only. Organize starts and stops it itself, talks to it on 127.0.0.1 and never downloads models. Off: sorting works by file type as before.</small></span><input v-model="draft.aiEnabled" type="checkbox" @change="save({ aiEnabled: draft.aiEnabled })" /></label>
        <div><span><b>Local models</b><small v-if="!status">Check which models are installed. Starting the local server can take a few seconds.</small><small v-else-if="!status.ollamaInstalled">Ollama is not installed. Install it from ollama.com and run “ollama pull nomic-embed-text” and “ollama pull qwen2.5:3b-instruct” in Terminal.</small><small v-else-if="status.error">The local model server did not start.</small><small v-else>{{ status.models?.length ?? 0 }} installed · vector math: {{ status.vectorBackend === 'accelerate' ? 'Apple Accelerate' : 'built-in' }}</small></span><button class="button secondary" :disabled="checking" @click="checkModels">{{ checking ? 'Checking…' : 'Check models' }}</button></div>
        <label><span><b>Embedding model</b><small>Reads a short, scrubbed summary of each file</small></span><select v-model="draft.aiEmbedModel" class="model-select" @change="save({ aiEmbedModel: draft.aiEmbedModel })"><option v-for="model in models.embed" :key="model" :value="model">{{ model }}</option></select></label>
        <label><span><b>Naming model</b><small>Names each group once; it never decides where files go</small></span><select v-model="draft.aiLlmModel" class="model-select" @change="save({ aiLlmModel: draft.aiLlmModel })"><option v-for="model in models.llm" :key="model" :value="model">{{ model }}</option></select></label>
        <label><span><b>Short descriptions</b><small>Adds up to five words per category. Off by default.</small></span><input v-model="draft.aiDescriptions" type="checkbox" @change="save({ aiDescriptions: draft.aiDescriptions })" /></label>
        <label><span><b>Match threshold</b><small>How similar a new file must be to a saved category (0.50–0.95). Higher means more files stay in Other.</small></span><input v-model.number="draft.aiThreshold" class="number-input" type="number" min="0.5" max="0.95" step="0.05" @change="save({ aiThreshold: draft.aiThreshold })" /></label>
        <div><span><b>Clear AI data</b><small>Deletes cached vectors, saved category examples and recent analyses. Files are not touched.</small></span><button class="button secondary danger" @click="confirmClear = true">Clear AI data</button></div>
        <p class="settings-note">Before any text reaches a model, emails, phone numbers, IBANs, card numbers, tax codes, IP addresses, keys and tokens are removed. This scrubbing is best-effort and cannot catch everything. File text is never stored; only number vectors are.</p>
      </section>
      <section class="settings-group"><h2>Appearance</h2><div><span><b>Theme</b><small>Follows system settings by default</small></span><div class="segments"><button v-for="theme in (['system','light','dark'] as const)" :key="theme" :class="{ active: store.theme === theme }" @click="save({ theme })">{{ { system: 'Follow system', light: 'Light', dark: 'Dark' }[theme] }}</button></div></div></section>
    </fieldset>
    <div v-if="confirmClear" class="modal-backdrop" @click.self="confirmClear = false">
      <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="clear-ai-title">
        <h2 id="clear-ai-title">Clear local AI data?</h2>
        <p>This deletes cached vectors, saved category examples and recent analyses. It cannot be undone, but your files and plans are not changed.</p>
        <div><button class="button secondary" @click="confirmClear = false">Cancel</button><button class="button primary" @click="clearAiData">Clear</button></div>
      </section>
    </div>
  </div>
</template>
