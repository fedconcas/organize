import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'
import './theme.css'
import './config.css'
import './analyze.css'

createApp(App).use(createPinia()).mount('#app')
