<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useAppStore } from '../stores/app'
import type { Profile } from '../types'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ saved: boolean }>()
const emit = defineEmits<{ loaded: [] }>()
const store = useAppStore()
const open = ref(false)
const confirmingRemove = ref(false)
const root = ref<HTMLElement>()

function close() { open.value = false; confirmingRemove.value = false }
function onDocumentClick(event: MouseEvent) { if (!root.value?.contains(event.target as Node)) close() }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') close() }
onMounted(() => { document.addEventListener('mousedown', onDocumentClick); document.addEventListener('keydown', onKeydown) })
onBeforeUnmount(() => { document.removeEventListener('mousedown', onDocumentClick); document.removeEventListener('keydown', onKeydown) })

function load(profile: Profile) {
  store.useProfile(profile)
  emit('loaded')
  close()
}
async function saveCopy() {
  store.profile.id = crypto.randomUUID()
  store.profile.name = `${store.profile.name} copy`.slice(0, 80)
  await store.saveProfile()
  close()
}
async function remove() {
  if (!confirmingRemove.value) { confirmingRemove.value = true; return }
  await store.deleteProfile(store.profile.id)
  close()
}
const ruleCount = (profile: Profile) => profile.parameters.typeRules?.filter((rule) => rule.enabled).length
</script>

<template>
  <div ref="root" class="menu-anchor">
    <button class="button secondary" :aria-expanded="open" aria-haspopup="menu" @click="open ? close() : (open = true)">
      <AppIcon name="bookmark" :size="16" />Plan library<span class="count-badge">{{ store.savedProfiles.length }}</span><AppIcon name="chevron" :size="14" />
    </button>
    <div v-if="open" class="popover profile-menu" role="menu">
      <header class="popover-head">Saved plans</header>
      <div v-if="store.savedProfiles.length" class="profile-list">
        <button v-for="profile in store.savedProfiles" :key="profile.id" role="menuitem" class="profile-item" :class="{ current: profile.id === store.profile.id }" @click="load(profile)">
          <span><b>{{ profile.name }}</b><small>{{ profile.sourceFolders.length }} sources<template v-if="ruleCount(profile) !== undefined">, {{ ruleCount(profile) }} categories</template></small></span>
          <em v-if="profile.id === store.profile.id">Current</em>
        </button>
      </div>
      <p v-else class="popover-empty">No saved plans yet. After saving you can switch here in one click.</p>
      <footer class="popover-actions">
        <button role="menuitem" @click="saveCopy"><AppIcon name="duplicate" :size="15" />Save as new plan</button>
        <button v-if="props.saved" role="menuitem" class="danger" @click="remove"><AppIcon name="trash" :size="15" />{{ confirmingRemove ? 'Click again to confirm removal' : 'Remove from library' }}</button>
      </footer>
    </div>
  </div>
</template>
