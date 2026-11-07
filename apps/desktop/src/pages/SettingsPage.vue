<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../stores/app'
import { pickDirectories, requestNotificationPermission } from '../api'
import type { Settings } from '../types'
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
      <section class="settings-group"><h2>Appearance</h2><div><span><b>Theme</b><small>Follows system settings by default</small></span><div class="segments"><button v-for="theme in (['system','light','dark'] as const)" :key="theme" :class="{ active: store.theme === theme }" @click="save({ theme })">{{ { system: 'Follow system', light: 'Light', dark: 'Dark' }[theme] }}</button></div></div></section>
    </fieldset>
  </div>
</template>
