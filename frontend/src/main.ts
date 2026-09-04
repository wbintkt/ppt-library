import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { applyTheme, currentTheme } from './theme'
import './styles.css'

// 挂载前应用已保存的主题（index.html 内联脚本已提前处理，此处兜底）
applyTheme(currentTheme.value)

createApp(App).use(router).mount('#app')
