<script setup lang="ts">
const props = defineProps<{ step: number }>()
const steps = ['Choose plan', 'Set folders', 'Scan', 'Preview', 'Organize', 'Result']
</script>

<template>
  <nav class="flow-stepper" aria-label="Organizing flow">
    <template v-for="(label, index) in steps" :key="label">
      <div class="flow-step" :aria-current="index + 1 === props.step ? 'step' : undefined" :class="{ done: index + 1 < props.step, current: index + 1 === props.step }">
        <span>{{ index + 1 < props.step ? '✓' : index + 1 }}</span>{{ label }}
      </div>
      <i v-if="index < steps.length - 1" :class="{ done: index + 1 < props.step }" />
    </template>
    <div class="flow-safe">♢ {{ props.step < 5 ? 'No files are changed before you confirm' : 'Where every file goes is recorded and can be undone' }}</div>
  </nav>
</template>
