<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
defineProps<{ title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
let previousFocus: HTMLElement | null = null
let previousOverflow = ''
onMounted(() => {
  previousFocus = document.activeElement as HTMLElement
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value?.showModal()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  document.body.style.overflow = previousOverflow
  if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
})
function backdrop(event: MouseEvent) {
  if (event.target !== dialog.value) return
  const bounds = dialog.value.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) emit('close')
}
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" class="app-dialog" :class="{ wide }" :aria-label="title" @cancel.prevent="emit('close')" @click="backdrop">
      <header class="dialog-header">
        <h2>{{ title }}</h2>
        <button type="button" class="icon-button" aria-label="关闭窗口" autofocus @click="emit('close')">×</button>
      </header>
      <div class="dialog-content"><slot /></div>
      <footer v-if="$slots.footer" class="dialog-footer"><slot name="footer" /></footer>
    </dialog>
  </Teleport>
</template>
<style scoped>
.app-dialog { position: fixed; inset: 0; margin: auto; padding: 0; width: min(680px, calc(100vw - 40px)); max-height: calc(100dvh - 64px); border: 1px solid var(--line); border-radius: 10px; background: var(--bg); color: var(--ink); box-shadow: 0 24px 80px #24232126; }
.app-dialog[open] { display: flex; flex-direction: column; }
.app-dialog.wide { width: min(1280px, calc(100vw - 48px)); }
.app-dialog::backdrop { background: #24232188; }
.dialog-header { display: flex; align-items: center; gap: 24px; padding: 18px 24px; border-bottom: 1px solid var(--line); }
.dialog-header h2 { flex: 1; min-width: 0; font-family: var(--sans); font-size: 16px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dialog-content { overflow-y: auto; min-height: 0; }
.dialog-footer { display: flex; gap: 12px; justify-content: flex-end; align-items: center; padding: 16px 24px; border-top: 1px solid var(--line); }
@media(max-width: 600px) { .app-dialog, .app-dialog.wide { width: calc(100vw - 20px); max-height: calc(100dvh - 24px); } .dialog-header, .dialog-footer { padding: 12px 16px; } .dialog-footer { flex-wrap: wrap; gap: 8px; } .dialog-footer :deep(.btn) { font-size: 12px; padding: 9px 10px; white-space: nowrap; } }
</style>
