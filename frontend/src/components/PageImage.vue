<script setup lang="ts">
import { ref, watch } from 'vue'
import { imageUrl } from '../api'
const props = defineProps<{ pageId: number; title: string; eager?: boolean }>()
const failed = ref(false)
const loaded = ref(false)
watch(() => props.pageId, () => { failed.value = false; loaded.value = false })
</script>
<template>
  <div class="page-image" :class="{ loaded }">
    <img v-if="!failed" :key="pageId" :src="imageUrl(pageId)" :alt="title" :loading="eager ? 'eager' : 'lazy'" decoding="async" @load="loaded = true" @error="failed = true" />
    <span v-else class="image-unavailable">预览图暂不可用</span>
  </div>
</template>
<style scoped>
.page-image { width: 100%; height: 100%; display: grid; place-items: center; background: var(--bg-deep); overflow: hidden; }
.page-image.loaded { background: #fff; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
.image-unavailable { color: var(--ink-soft); font-size: 13px; }
</style>
