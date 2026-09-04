import { ref } from 'vue'

export type ThemeId = 'tower' | 'green'

export interface ThemeOption {
  id: ThemeId
  name: string
  desc: string
  /** 预览色块（背景 / 主色 / 主容器 / 描边） */
  swatches: string[]
}

export const THEMES: ThemeOption[] = [
  {
    id: 'tower',
    name: '铁塔红 · 和风',
    desc: '日式和风原版，中国铁塔品牌红主色',
    swatches: ['#faf9f7', '#e60012', '#f7e6e7', '#f0c9cc'],
  },
  {
    id: 'green',
    name: '青绿 · M3 Expressive',
    desc: '灵感来自 Material 3 Expressive 绿色预设：沉稳青绿主色 + 薄荷绿容器 + 微绿白底',
    swatches: ['#f6fbf4', '#2e6a45', '#b0f1c2', '#d5e5da'],
  },
]

const STORAGE_KEY = 'ppt_theme'

export function readStoredTheme(): ThemeId {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'green' ? 'green' : 'tower'
  } catch {
    return 'tower'
  }
}

export function applyTheme(id: ThemeId) {
  if (id === 'green') {
    document.documentElement.setAttribute('data-theme', 'green')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
}

/** 当前主题（响应式，供界面绑定） */
export const currentTheme = ref<ThemeId>(readStoredTheme())

export function setTheme(id: ThemeId) {
  currentTheme.value = id
  applyTheme(id)
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* 忽略隐私模式等写入失败 */
  }
}
