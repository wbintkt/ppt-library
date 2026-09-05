<script setup lang="ts">
import { toastState } from './toast'
</script>

<template>
  <div role="status" aria-live="polite" class="toast" :class="{ error: toastState.type === 'error' }" v-if="toastState.visible">
    {{ toastState.msg }}
  </div>
</template>
