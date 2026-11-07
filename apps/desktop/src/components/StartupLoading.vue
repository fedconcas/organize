<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ state: 'loading' | 'ready' | 'error'; error?: string }>()
defineEmits<{ retry: [] }>()
const failed = computed(() => props.state === 'error')
const slow = ref(false)
let slowTimer: ReturnType<typeof setTimeout> | undefined
watch(() => props.state, (state) => {
  clearTimeout(slowTimer)
  slow.value = false
  if (state === 'loading') slowTimer = setTimeout(() => { slow.value = true }, 8000)
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(slowTimer))
</script>

<template>
  <section class="startup-screen" :class="{ 'startup-screen--failed': failed }" :role="failed ? 'alert' : 'status'" :aria-busy="!failed" aria-live="polite" aria-atomic="true">
    <div class="startup-mark" aria-hidden="true">
      <span class="startup-halo" />
      <svg class="startup-o" viewBox="0 0 112 112" fill="none">
        <defs><linearGradient id="startup-o-live" x1="27" y1="19" x2="85" y2="93" gradientUnits="userSpaceOnUse"><stop class="o-light" /><stop class="o-mid" offset="0.5" /><stop class="o-deep" offset="1" /></linearGradient></defs>
        <ellipse cx="56" cy="56" rx="29" ry="37" stroke="url(#startup-o-live)" stroke-width="9" />
      </svg>
    </div>
    <h1 class="startup-title">{{ failed ? 'Smart Organize can’t start right now' : 'Preparing Smart Organize' }}</h1>
    <p v-if="failed" class="startup-detail startup-error">{{ error || 'The organizing engine failed to start. Please retry.' }}</p>
    <p v-else class="startup-detail">{{ slow ? 'The first launch may take a moment, please wait…' : 'Starting the local engine, please wait…' }}</p>
    <button v-if="failed" class="startup-retry" @click="$emit('retry')">Reload</button>
  </section>
</template>
