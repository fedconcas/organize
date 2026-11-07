<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import { openLegalResource } from '../api'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
type LegalData = typeof import('../generated/legal-notices.json')
const data = ref<LegalData>()
const search = ref('')
const status = ref('')
const tab = ref<'project' | 'components' | 'sources' | 'brand'>('project')
const tabs = [
  { id: 'project', label: 'Project license' }, { id: 'components', label: 'Third-party components' },
  { id: 'sources', label: 'MPL Source' }, { id: 'brand', label: 'Independent branding' },
] as const
watch(() => props.show, async (show) => {
  if (!show || data.value) return
  try { data.value = (await import('../generated/legal-notices.json')).default }
  catch { status.value = 'Failed to load license materials; check the package Contents/Resources/legal or reinstall.' }
}, { immediate: true })
const components = computed(() => (data.value?.components ?? []).filter((p) =>
  `${p.name} ${p.version} ${p.license} ${p.ecosystem}`.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()),
))
async function open(resource: 'licenses' | 'mpl-sources') {
  try {
    status.value = await openLegalResource(resource)
      ? 'Opened the license resources inside the package.'
      : 'This is a browser demo. The desktop package includes all materials; developers can check the repository legal/generated. '
  } catch (error) { status.value = error instanceof Error ? error.message : String(error) }
}
</script>

<template>
  <NModal :show="show" preset="card" title="Open-source licenses and source code" :style="{ width: 'min(900px, calc(100vw - 48px))' }" :bordered="false" @update:show="emit('update:show', $event)">
    <div class="license-actions"><button class="button secondary" @click="open('licenses')">Open licenses folder</button><button class="button secondary" @click="open('mpl-sources')">Open MPL source archive</button></div>
    <p v-if="status" class="license-status" role="status">{{ status }}</p>
    <nav class="license-tabs" aria-label="License notice categories"><button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="tab = item.id">{{ item.label }}</button></nav>
    <div class="license-content" tabindex="0" aria-label="Full license text, scrollable">
      <template v-if="data">
        <template v-if="tab === 'project'"><h3>Organize · Independent desktop derivative project</h3><p>Based on Thomas Feldmann’s organize, keeping the upstream MIT license and attribution. New desktop code and original icons are provided under MIT; third-party components follow their own licenses. The software license grants no third-party trademark rights.</p><pre>{{ data.mit }}</pre></template>
        <template v-else-if="tab === 'components'">
          <label class="license-search">Search components, versions or licenses<input v-model="search" type="search" placeholder="e.g. option-ext / MPL / Python" /></label>
          <p>{{ components.length }} results · {{ data.target }}. The list conservatively covers runtime and build dependencies; it does not mean everything is linked into the app.</p>
          <details v-for="p in components" :key="`${p.ecosystem}:${p.name}@${p.version}`"><summary>{{ p.name }} {{ p.version }} · {{ p.license }}</summary><p>{{ p.ecosystem }} · {{ p.scope }}</p><p class="license-source">{{ p.source }}</p><section v-for="file in p.files" :key="file.name"><h4>{{ file.name }}</h4><pre>{{ file.text }}</pre></section></details>
          <p v-if="!components.length">No matching components found.</p>
        </template>
        <pre v-else-if="tab === 'sources'">{{ data.sources }}</pre>
        <pre v-else>{{ data.brand }}</pre>
      </template>
      <p v-else>Loading license materials…</p>
    </div>
  </NModal>
</template>

<style scoped>
.license-actions, .license-tabs { display: flex; gap: 10px; flex-wrap: wrap; }
.license-tabs { margin: 18px 0 12px; border-bottom: 1px solid var(--border, #ddd); padding-bottom: 10px; }
.license-tabs button { cursor: pointer; border: 0; border-radius: 8px; padding: 8px 14px; background: transparent; color: inherit; }
.license-tabs button.active { background: #218d8320; color: #228f84; }
.license-content { max-height: min(58vh, 560px); overflow: auto; padding-right: 8px; line-height: 1.65; }
.license-content pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.75 ui-monospace, monospace; }
.license-content details { padding: 12px 0; border-bottom: 1px solid var(--border, #ddd); }
.license-content summary { cursor: pointer; overflow-wrap: anywhere; }
.license-search { display: grid; gap: 6px; }
.license-search input { padding: 10px 12px; border: 1px solid #8a9b9d66; border-radius: 8px; color: inherit; background: transparent; }
.license-source, .license-status { overflow-wrap: anywhere; }
</style>
