<script setup lang="ts">
import { toastState } from './toast'
</script>

<template>
  <div class="toast" :class="{ error: toastState.type === 'error' }" v-if="toastState.visible">
    {{ toastState.msg }}
  </div>
</template>
