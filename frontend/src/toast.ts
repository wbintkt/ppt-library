// 轻量全局 toast
import { reactive } from 'vue'

export const toastState = reactive<{ msg: string; type: 'info' | 'error'; visible: boolean }>({
  msg: '',
  type: 'info',
  visible: false,
})

let timer: ReturnType<typeof setTimeout> | null = null

export function toast(msg: string, type: 'info' | 'error' = 'info') {
  toastState.msg = msg
  toastState.type = type
  toastState.visible = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { toastState.visible = false }, 3200)
}
