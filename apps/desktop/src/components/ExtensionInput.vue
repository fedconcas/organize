<script setup lang="ts">
import { ref } from 'vue'
import { parseExtensions, validExtension } from '../profiles'
import AppIcon from './AppIcon.vue'

const model = defineModel<string[]>({ required: true })
const props = defineProps<{ label: string; conflicts: Map<string, string[]> }>()
const draft = ref('')
const input = ref<HTMLInputElement>()

function commit() {
  const values = parseExtensions(draft.value).filter((value) => !model.value.includes(value))
  if (values.length) model.value = [...model.value, ...new Set(values)]
  draft.value = ''
}
function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  draft.value = value
  if (/[\s,, ;; ]/.test(value)) commit()
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') { event.preventDefault(); commit() }
  else if (event.key === 'Backspace' && !draft.value && model.value.length) model.value = model.value.slice(0, -1)
}
function remove(extension: string) {
  model.value = model.value.filter((value) => value !== extension)
  input.value?.focus()
}
function chipTitle(extension: string) {
  if (!validExtension(extension)) return 'Extensions may only contain letters, digits, -, _ and +'
  const owners = props.conflicts.get(extension)
  return owners?.length ? `also belongs to “${owners.join('”“')}”` : undefined
}
</script>

<template>
  <div class="ext-input" @click="input?.focus()">
    <span v-for="extension in model" :key="extension" class="ext-chip" :class="{ conflict: chipTitle(extension) }" :title="chipTitle(extension)">
      <i>.</i>{{ extension }}
      <button type="button" :aria-label="`Remove extension ${extension}`" @click.stop="remove(extension)"><AppIcon name="close" :size="11" /></button>
    </span>
    <input ref="input" :value="draft" :aria-label="label" :placeholder="model.length ? 'Add more' : 'Enter extensions, e.g.  pdf'" @input="onInput" @keydown="onKeydown" @blur="commit" />
  </div>
</template>
