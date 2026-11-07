<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, pickDiagnosticPath, revealLocalPath } from '../api'
import PageHeader from '../components/PageHeader.vue'
import appIcon from '../assets/app-icon.png'
import LicenseDialog from '../components/LicenseDialog.vue'

const versions = ref({ engine: '—', organize: '—' })
const dataDir = ref('')
const exportStatus = ref('')
const licenseOpen = ref(false)
onMounted(async () => {
  const [loadedVersions, initial] = await Promise.all([
    api.request<{ engine: string; organize: string }>('app.version'),
    api.request<{ dataDir: string }>('app.initialize'),
  ])
  versions.value = loadedVersions
  dataDir.value = initial.dataDir
})
async function exportDiagnostics() {
  const destination = await pickDiagnosticPath()
  if (!destination) return
  const result = await api.request<{ path: string }>('diagnostics.export', { destination })
  exportStatus.value = `Saved to ${result.path}`
}
</script>

<template>
  <div class="page scroll-page narrow-page">
    <PageHeader title="About & diagnostics" description="Version, privacy and local diagnostic tools." />
    <section class="about-hero panel"><span class="about-app-icon"><img :src="appIcon" alt="" /></span><div><h2>Organize</h2><p>A safe, previewable, undoable file organizing assistant</p><small>Independent derivative project · based on Thomas Feldmann’s organize</small></div><dl><dt>App version</dt><dd>0.1.0</dd><dt>Organizing engine</dt><dd>{{ versions.engine }}</dd><dt>organize</dt><dd>{{ versions.organize }}</dd></dl></section>
    <section class="settings-group"><h2>Diagnostics</h2><div><span><b>App data folder</b><small>{{ dataDir || 'Reading…' }}</small></span><button class="button secondary" :disabled="!dataDir" @click="revealLocalPath(dataDir)">Open</button></div><div><span><b>Export diagnostics bundle</b><small>{{ exportStatus || 'Stored only on your computer, never uploaded automatically' }}</small></span><button class="button primary" @click="exportDiagnostics">Export</button></div></section>
    <section class="settings-group"><h2>Notes</h2><div><span><b>Privacy notes</b><small>The app uploads no files or file names</small></span></div><button class="link-row" @click="licenseOpen = true"><span><b>Open-source licenses and source code</b><small>MIT Attribution, full third-party licenses, MPL corresponding source and independent branding notes</small></span><i>›</i></button><div><span><b>Independent project</b><small>Not the official upstream desktop version; not affiliated with or endorsed by Microsoft, Apple or MacPaw.</small></span></div></section>
    <LicenseDialog v-model:show="licenseOpen" />
  </div>
</template>
