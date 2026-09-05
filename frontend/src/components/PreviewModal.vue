<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { api, type PageSummary } from '../api'
import { toast } from '../toast'
import { saveBlob } from '../download'
import AppDialog from './AppDialog.vue'
import PageImage from './PageImage.vue'

const props = defineProps<{ pageId: number; title: string; pageIds?: number[]; selectedIds?: number[] }>()
const emit = defineEmits<{ close: []; toggle: [page: PageSummary] }>()
const page = ref<PageSummary | null>(null)
const similar = ref<Awaited<ReturnType<typeof api.similarPages>>>([])
const loading = ref(true)
const error = ref('')
const downloading = ref(false)
const currentId = ref(props.pageId)
const expanded = ref(false)
const currentIndex = computed(() => props.pageIds?.indexOf(currentId.value) ?? -1)
const canPrevious = computed(() => currentIndex.value > 0)
const canNext = computed(() => currentIndex.value >= 0 && currentIndex.value < (props.pageIds?.length ?? 0) - 1)
const selected = computed(() => props.selectedIds?.includes(currentId.value))
const heading = computed(() => page.value ? `${page.value.title || '页面预览'} · 第 ${page.value.page_no} 页` : '页面预览')
let generation = 0
watch(() => props.pageId, (id) => { currentId.value = id }, { immediate: true })
watch(currentId, load, { immediate: true })
onMounted(() => document.addEventListener('keydown', arrowNavigation))
onBeforeUnmount(() => { generation++; document.removeEventListener('keydown', arrowNavigation) })
async function load() {
  const id = ++generation
  const pageId = currentId.value
  loading.value = true
  error.value = ''
  page.value = null
  similar.value = []
  // Recommendations are independent: a slow recommendation request must not delay the main page.
  api.similarPages(pageId, 6).then(items => {
    if (id === generation) similar.value = items
  }).catch(() => {})
  try {
    const result = await api.getPage(pageId)
    if (id === generation) page.value = result
  } catch (e: any) {
    if (id === generation) error.value = e.message || '页面加载失败'
  } finally {
    if (id === generation) loading.value = false
  }
}
function step(direction: number) {
  const next = props.pageIds?.[currentIndex.value + direction]
  if (currentIndex.value >= 0 && next) currentId.value = next
}
function arrowNavigation(event: KeyboardEvent) {
  if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable="true"]')) return
  if (event.key === 'ArrowLeft' && canPrevious.value) { event.preventDefault(); step(-1) }
  if (event.key === 'ArrowRight' && canNext.value) { event.preventDefault(); step(1) }
}
async function downloadPage() {
  if (!page.value || downloading.value) return
  const target = page.value
  downloading.value = true
  try {
    saveBlob(await api.exportPages([target.id]), `${target.title || '页面'}_第${target.page_no}页.pptx`)
    toast('本页已导出为 PPTX')
  } catch (e: any) { toast(e.message || '导出本页失败', 'error') }
  finally { downloading.value = false }
}
</script>
<template>
  <AppDialog :title="heading" wide @close="emit('close')">
    <div class="preview-workspace">
      <div class="preview-toolbar">
        <div class="preview-paging" v-if="pageIds?.length">
          <button class="icon-button" aria-label="上一条搜索结果" :disabled="!canPrevious" @click="step(-1)">←</button>
          <span>{{ currentIndex >= 0 ? `${currentIndex + 1} / ${pageIds.length}` : '相关页面' }}</span>
          <button class="icon-button" aria-label="下一条搜索结果" :disabled="!canNext" @click="step(1)">→</button>
        </div>
        <button class="text-button enlarge" :aria-pressed="expanded" @click="expanded = !expanded">{{ expanded ? '显示文本' : '放大图片' }}</button>
      </div>
      <div v-if="error" class="preview-error" role="alert"><p>{{ error }}</p><button class="btn" @click="load">重新加载</button></div>
      <div v-else class="preview-body" :class="{ expanded }">
        <div class="preview-image"><PageImage :page-id="currentId" :title="page?.title || title" eager /></div>
        <aside v-if="!expanded" class="preview-text">
          <h3>本页内容</h3><p v-if="loading" role="status" class="loading-dots">正在加载</p><p v-else>{{ page?.text || '本页暂无可提取的文本，请查看左侧预览。' }}</p>
        </aside>
      </div>
      <section v-if="similar.length" class="similar-section" aria-label="相关页面">
        <h3>相关页面<span>继续发现有用的内容</span></h3>
        <div class="similar-list"><button v-for="item in similar" :key="item.page_id" :aria-label="`预览相关页面：${item.title}`" class="similar-item" @click="currentId = item.page_id"><div><PageImage :page-id="item.page_id" :title="item.title" /></div><span>{{ item.title }}</span></button></div>
      </section>
    </div>
    <template #footer>
      <button v-if="page && selectedIds !== undefined" class="btn selection-action" :class="{ 'is-added': selected }" :aria-pressed="selected" @click="emit('toggle', page)">{{ selected ? '✓ 已选择' : '＋ 选择此页' }}</button>
      <router-link v-if="page" :to="{ name: 'file', params: { id: page.file_id } }" class="btn" @click="emit('close')">浏览整份 PPT</router-link>
      <button class="btn primary" :disabled="!page || downloading" @click="downloadPage">{{ downloading ? '正在生成…' : '导出本页' }}</button>
    </template>
  </AppDialog>
</template>
<style scoped>
.preview-workspace { padding: 0 24px 24px; }
.preview-toolbar { display: flex; align-items: center; padding: 12px 0; min-height: 56px; }
.preview-paging { display: flex; align-items: center; gap: 12px; }
.preview-paging span { color: var(--ink-soft); font-size: 12px; font-variant-numeric: tabular-nums; }
.enlarge { margin-left: auto; }
.preview-body { display: grid; grid-template-columns: minmax(0, 3fr) minmax(220px, 1fr); gap: 24px; }
.preview-body.expanded { grid-template-columns: 1fr; }
.preview-image { aspect-ratio: 16/9; align-self: start; border: 1px solid var(--line); overflow: hidden; border-radius: 4px; }
.expanded .preview-image { max-height: 65vh; aspect-ratio: auto; height: 65vh; }
.preview-text { max-height: 44vh; overflow: auto; }
.preview-text h3 { font-family: var(--sans); font-size: 13px; font-weight: 500; margin-bottom: 12px; }
.preview-text p { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.9; color: var(--ink-soft); }
.preview-error { text-align: center; padding: 48px; }
.preview-error p { margin-bottom: 20px; }
.similar-section { margin-top: 24px; border-top: 1px solid var(--line); padding-top: 20px; }
.similar-section h3 { font-family: var(--sans); font-size: 13px; font-weight: 500; margin-bottom: 12px; }
.similar-section h3 span { font-size: 12px; color: var(--ink-faint); margin-left: 14px; font-weight: 400; }
.similar-list { display: flex; gap: 14px; overflow: auto; padding-bottom: 4px; }
.similar-item { flex: 0 0 144px; padding: 0; border: 0; background: none; text-align: left; cursor: pointer; color: var(--ink-soft); }
.similar-item > div { aspect-ratio: 16/9; border: 1px solid var(--line); border-radius: 4px; overflow: hidden; }
.similar-item:hover > div { border-color: var(--brand); }
.similar-item > span { display: block; font: 12px var(--sans); margin-top: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selection-action { margin-right: auto; }
.is-added { color: var(--brand); background: var(--brand-soft); border-color: var(--brand); }
@media(max-width: 720px) { .preview-body { grid-template-columns: 1fr; gap: 20px; } .preview-text { max-height: 180px; } .preview-workspace { padding: 0 16px 16px; } .selection-action { margin-right: 0; } }
</style>
