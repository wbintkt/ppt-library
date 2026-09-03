<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, imageUrl, type PageSummary } from '../api'
import { toast } from '../toast'

const props = defineProps<{ pageId: number; title: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const page = ref<PageSummary | null>(null)
const similar = ref<{ page_id: number; file_id: number; page_no: number; title: string; text: string; file_name: string; score: number }[]>([])
const loading = ref(true)
const downloading = ref(false)
const currentId = ref(props.pageId)

onMounted(load)
watch(() => props.pageId, (v) => { currentId.value = v; load() })

async function load() {
  loading.value = true
  page.value = null
  similar.value = []
  try {
    const [p, sim] = await Promise.all([
      api.getPage(currentId.value),
      api.similarPages(currentId.value, 6).catch(() => []),
    ])
    page.value = p
    similar.value = sim
  } catch { /* ignore */ } finally {
    loading.value = false
  }
}

function switchTo(id: number) {
  currentId.value = id
  load()
}

async function downloadPage() {
  if (!page.value || downloading.value) return
  downloading.value = true
  try {
    const blob = await api.exportPages([page.value.id])
    const base = (page.value.file_name || '页面').replace(/\.pptx?$/i, '')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${base}_第${page.value.page_no}页.pptx`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast(`已导出本页为 PPTX：${base} · 第 ${page.value.page_no} 页`)
  } catch (e: any) {
    toast(e.message || '导出本页失败', 'error')
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-head">
        <span class="modal-title">{{ title }}</span>
        <button class="modal-close" @click="emit('close')">×</button>
      </div>
      <div class="modal-body preview-body">
        <div class="preview-img">
          <img v-if="!loading" :key="currentId" :src="imageUrl(currentId)" alt="页面预览" />
          <div v-else class="loading-dots preview-loading">加载中</div>
        </div>
        <div class="preview-side" v-if="page">
          <div class="side-block">
            <h4>◆ 本页文本</h4>
            <p class="side-text">{{ page.text || '（本页未提取到文本，可查看图片内容）' }}</p>
          </div>
          <div class="side-block" v-if="page.tags">
            <h4>◆ 标签</h4>
            <span class="tag">{{ page.tags }}</span>
          </div>
          <div class="side-block">
            <h4>◆ 来源文件</h4>
            <p class="side-file">{{ page.file_name }}</p>
            <p class="side-sub">第 {{ page.page_no }} 页 · {{ page.file_category || '未分类' }}</p>
          </div>
          <div class="side-actions">
            <button class="btn primary btn-sm" :disabled="downloading" @click="downloadPage">
              {{ downloading ? '生成中…' : '下载本页' }}
            </button>
            <router-link :to="{ name: 'file', params: { id: page.file_id } }" class="btn btn-sm">文件详情</router-link>
          </div>
        </div>
      </div>
      <div class="similar-bar" v-if="similar.length">
        <div class="similar-head">
          <span class="similar-title">◆ 相似页面</span>
          <span class="similar-hint">点击切换预览</span>
        </div>
        <div class="similar-list">
          <div v-for="s in similar" :key="s.page_id" class="similar-item" @click="switchTo(s.page_id)">
            <img :src="imageUrl(s.page_id)" loading="lazy" :alt="s.title" />
            <span class="sim-no">P{{ s.page_no }}</span>
            <span class="sim-score" v-if="s.score > 0 && s.score <= 1">{{ (s.score * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preview-body { display: flex; gap: 22px; }
.preview-img { flex: 1.4; display: flex; align-items: flex-start; justify-content: center; background: var(--bg-deep); border: 1px solid var(--brand-line); border-radius: 10px; padding: 12px; min-height: 380px; }
.preview-img img { max-width: 100%; max-height: 66vh; object-fit: contain; border-radius: 4px; box-shadow: 0 4px 18px rgba(0,0,0,0.12); }
.preview-loading { color: var(--ink-faint); padding: 40px; }
.preview-side { flex: 1; display: flex; flex-direction: column; gap: 18px; max-width: 380px; }
.side-block h4 { font-size: 13px; color: var(--brand-deep); margin-bottom: 8px; letter-spacing: 1px; }
.side-text { font-size: 13px; color: var(--ink-soft); max-height: 42vh; overflow: auto; white-space: pre-wrap; background: var(--white); border: 1px solid var(--brand-line); border-radius: 8px; padding: 10px 12px; }
.side-file { font-size: 13px; color: var(--ink); word-break: break-all; }
.side-sub { font-size: 12px; color: var(--ink-faint); margin-top: 4px; }
.side-actions { display: flex; gap: 10px; margin-top: 4px; }

.similar-bar { border-top: 1px solid var(--brand-line); padding: 14px 24px 16px; }
.similar-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.similar-title { font-family: var(--serif); font-size: 13.5px; font-weight: 700; color: var(--brand-deep); }
.similar-hint { font-size: 11.5px; color: var(--ink-faint); }
.similar-list { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }
.similar-item { position: relative; flex-shrink: 0; width: 120px; aspect-ratio: 16/10; border-radius: 8px; overflow: hidden; border: 1px solid var(--brand-line); cursor: pointer; transition: all 0.2s; background: var(--bg-deep); }
.similar-item:hover { transform: translateY(-2px); box-shadow: var(--shadow-hover); border-color: var(--brand); }
.similar-item img { width: 100%; height: 100%; object-fit: contain; }
.sim-no { position: absolute; left: 5px; bottom: 5px; background: rgba(45,42,38,0.72); color: #f3ece2; font-size: 10px; padding: 1px 7px; border-radius: 999px; }
.sim-score { position: absolute; right: 5px; top: 5px; background: var(--brand); color: #fff; font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 999px; }
</style>
