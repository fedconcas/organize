<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import { darkTheme, NConfigProvider, NMessageProvider, type GlobalThemeOverrides } from 'naive-ui'
import AppSidebar from './components/AppSidebar.vue'
import FlowStepper from './components/FlowStepper.vue'
import HomePage from './pages/HomePage.vue'
import AnalyzePage from './pages/AnalyzePage.vue'
import ConfigPage from './pages/ConfigPage.vue'
import ScanPage from './pages/ScanPage.vue'
import PreviewPage from './pages/PreviewPage.vue'
import DuplicatesPage from './pages/DuplicatesPage.vue'
import ExecutingPage from './pages/ExecutingPage.vue'
import ResultPage from './pages/ResultPage.vue'
import HistoryPage from './pages/HistoryPage.vue'
import QuarantinePage from './pages/QuarantinePage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import AboutPage from './pages/AboutPage.vue'
import OnboardingPage from './pages/OnboardingPage.vue'
import UndoPage from './pages/UndoPage.vue'
import StartupLoading from './components/StartupLoading.vue'
import { useAppStore } from './stores/app'
import type { ViewName } from './types'

const store = useAppStore()
const pages = { onboarding: OnboardingPage, home: HomePage, analyze: AnalyzePage, config: ConfigPage, scan: ScanPage, preview: PreviewPage, duplicates: DuplicatesPage, executing: ExecutingPage, result: ResultPage, history: HistoryPage, undo: UndoPage, quarantine: QuarantinePage, settings: SettingsPage, about: AboutPage }
const current = computed(() => pages[store.view as keyof typeof pages] ?? HomePage)
// With category discovery the by-type flow gains a 'Categories' step after choosing the plan.
const withCategories = computed(() => store.profile.presetType === 'by-type' && (store.settings.aiEnabled || store.view === 'analyze' || Boolean(store.fromAnalysisId)))
const flowSteps: Partial<Record<ViewName, number>> = { analyze: 2, config: 2, scan: 3, preview: 4, duplicates: 4, executing: 5, result: 6 }
const flowStep = computed(() => {
  const step = flowSteps[store.view] ?? 0
  return withCategories.value && step && store.view !== 'analyze' ? step + 1 : step
})
const themeOverrides: GlobalThemeOverrides = { common: { primaryColor: '#79E6DA', successColor: '#79E6BB', warningColor: '#FFC986', errorColor: '#FF9BAA', bodyColor: '#211940', cardColor: '#342950', borderColor: '#514565', textColor1: '#F6F3FF', textColor2: '#C5BDD9', textColor3: '#A99DBF', borderRadius: '12px' } }
const backgrounded = ref(document.hidden)
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(systemTheme.matches)
const isDark = computed(() => store.theme === 'dark' || (store.theme === 'system' && systemDark.value))
function updateSystemTheme() { systemDark.value = systemTheme.matches }
systemTheme.addEventListener('change', updateSystemTheme)
watchEffect(() => { document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light' })
function updateVisibility() { backgrounded.value = document.hidden }
document.addEventListener('visibilitychange', updateVisibility)
onBeforeUnmount(() => document.removeEventListener('visibilitychange', updateVisibility))
onBeforeUnmount(() => systemTheme.removeEventListener('change', updateSystemTheme))
onMounted(() => store.initialize())
</script>

<template>
  <NConfigProvider class="app-provider" :theme="isDark ? darkTheme : null" :theme-overrides="isDark ? themeOverrides : {}">
    <NMessageProvider>
      <div class="window-shell" :class="{ 'motion-paused': backgrounded }">
        <div class="app-body">
          <AppSidebar v-if="store.startupState === 'ready' && store.view !== 'onboarding'" />
          <main class="main-content">
            <StartupLoading v-if="store.startupState !== 'ready'" :state="store.startupState" :error="store.startupError" @retry="store.initialize()" />
            <template v-else>
              <FlowStepper v-if="flowStep" :step="flowStep" :with-categories="withCategories" />
              <div v-if="store.error" class="global-error"><b>Something went wrong</b><span>{{ store.error }}</span><button @click="store.error = undefined">×</button></div>
              <div v-if="store.notice" class="global-notice" role="status"><span>{{ store.notice }}</span><button @click="store.notice = ''">×</button></div>
              <Transition name="view" mode="out-in">
                <component :is="current" :key="store.view" />
              </Transition>
            </template>
          </main>
        </div>
        <footer class="app-statusbar" role="status" aria-live="polite">
          <span><i :class="{ ready: store.engineReady }" aria-hidden="true" />{{ store.engineReady ? 'Organizing engine ready' : store.startupState === 'error' ? 'Organizing engine not ready' : 'Starting the organizing engine' }}</span>
        </footer>
      </div>
    </NMessageProvider>
  </NConfigProvider>
</template>
