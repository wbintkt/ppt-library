<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type ProcessingInfo, type FileSummary } from '../api'
import { toast } from '../toast'
import UploadModal from '../components/UploadModal.vue'
import DuplicateReview from '../components/DuplicateReview.vue'

const router = useRouter()
const files = ref<FileSummary[]>([])
const total = ref(0)
const category = ref('')
const categories = ref<{ category: string; count: number }[]>([])
const q = ref('')
const page = ref(1)
const pageSize = 30
const loading = ref(false)
const showUpload = ref(false)
const overview=ref<Record<number,ProcessingInfo>>({})
const showDuplicates=ref(false),revision=ref(0)
const pendingCount=computed(()=>Object.values(overview.value).reduce((n,s)=>n+s.pending_count,0))
let timer: ReturnType<typeof setInterval> | null = null

const processing = computed(() => files.value.filter(f => ['parsing','embedding','appending','enriching'].includes(f.status)))

async function load() {
  loading.value = true
  try {
    const params: Record<string, string | number> = { page: page.value, page_size: pageSize }
    if (category.value) params.category = category.value
    if (q.value.trim()) params.q = q.value.trim()
    const resp = await api.listFiles(params)
    files.value = resp.items
    total.value = resp.total
    const next=(await api.management()).files
    for(const [id,info] of Object.entries(next)){
      if(info.pending_count>(overview.value[Number(id)]?.pending_count||0) && overview.value[Number(id)]) toast(`发现 ${info.pending_count} 组相似页面，可在相似检测中处理`)
    }
    overview.value=next
    revision.value++
  } catch (e: any) {
    toast(e.message || '加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  // 有任务在处理时轮询刷新
  if (processing.value.length) await load()
}

async function loadCategories() {
  try { categories.value = await api.categories() } catch { /* ignore */ }
}

function statusLabel(s: string) {
  return { ready: '已完成', ready_limited: '可检索*', parsing: '解析中', embedding: '向量化中', failed: '失败', appending:'追加页面中', enriching:'生成标签 / 相似检测' }[s] || s
}

async function remove(f: FileSummary) {
  if (!confirm(`确认删除「${f.name}」及其全部页面素材？`)) return
  try {
    await api.deleteFile(f.id)
    toast('已删除')
    load()
  } catch (e: any) {
    toast(e.message || '删除失败', 'error')
  }
}

async function reindex(f: FileSummary) {
  if (!confirm(`重新解析「${f.name}」？（已配置 API Key 时将重新生成向量）`)) return
  try {
    await api.reindex(f.id)
    toast('已加入重新解析队列')
    load()
  } catch (e: any) {
    toast(e.message || '操作失败', 'error')
  }
}

function fmtSize(n: number) {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(t: string) {
  return t ? t.replace('T', ' ').slice(0, 16) : ''
}

onMounted(() => {
  load()
  loadCategories()
  timer = setInterval(refreshStatus, 6000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="library-view">
    <div class="lib-head fade-up">
      <div>
        <h2 class="lib-title">素材库</h2>
        <p class="lib-sub">共 {{ total }} 个 PPT · {{ processing.length ? `${processing.length} 个正在处理` : '全部就绪' }}</p>
      </div>
      <div class="lib-head-actions"><button class="btn" :class="{primary:pendingCount>0}" @click="showDuplicates=!showDuplicates">相似检测{{pendingCount?` · ${pendingCount} 组`:''}}</button><button class="btn primary" @click="showUpload = true">＋ 上传 PPT</button></div>
    </div>

    <DuplicateReview v-if="showDuplicates" :revision="revision" @changed="load"/>
    <div class="lib-filters fade-up fade-up-1">
      <div class="cats">
        <button class="chip" :class="{ active: category === '' }" @click="category = ''; page = 1; load()">全部</button>
        <button v-for="c in categories" :key="c.category" class="chip" :class="{ active: category === c.category }"
          @click="category = c.category; page = 1; load()">{{ c.category }}<span class="chip-count">{{ c.count }}</span></button>
      </div>
      <input v-model="q" class="text-input lib-search" placeholder="按文件名 / 标签筛选…" @keyup.enter="page = 1; load()" />
    </div>

    <div v-if="loading && !files.length" class="empty-state"><span class="loading-dots">加载中</span></div>
    <div v-else-if="!files.length" class="empty-state fade-up">
      <span class="icon">◇</span>
      <p>素材库还是空的</p>
      <p class="hint">上传第一个 PPT，系统将自动逐页解析入库</p>
    </div>

    <div v-else class="file-list">
      <div v-for="(f, i) in files" :key="f.id" class="card file-row fade-up" :class="'fade-up-' + ((i % 3) + 1)" @click="router.push(`/file/${f.id}`)">
        <div class="file-icon">◆</div>
        <div class="file-info">
          <div class="file-top">
            <span class="file-name">{{ f.name }}</span>
            <span class="badge" :class="f.status">{{ statusLabel(f.status) }}</span>
            <span v-if="overview[f.id]?.pending_count" class="duplicate-count">{{overview[f.id].pending_count}} 组相似页</span>
          </div>
          <div class="file-meta">
            <span class="tag">{{ f.category }}</span>
            <span v-if="f.tags" class="file-tags">{{ f.tags }}</span>
            <span class="file-detail">{{ f.page_count }} 页 · {{ fmtSize(f.file_size) }}</span>
            <span class="file-detail" v-if="f.source">· {{ f.source }}</span>
            <span class="file-detail">· {{ fmtTime(f.upload_time) }}</span>
          </div>
          <div class="progress-line" v-if="['parsing','embedding','appending','enriching'].includes(f.status)">
            <div class="bar"><div class="bar-inner" :style="{ width: f.progress + '%' }"></div></div>
            <span class="bar-text">{{ f.progress }}%</span>
          </div>
          <p class="file-error" v-if="f.status === 'failed'">{{ f.error_message }}</p>
          <p class="file-error soft" v-else-if="f.status === 'ready_limited'">全文检索模式 · 配置 API Key 后自动升级语义检索</p>
        </div>
        <div class="file-actions" @click.stop>
          <button class="btn btn-sm" @click="router.push(`/file/${f.id}`)">浏览页面</button>
          <a class="btn btn-sm" :href="api.downloadUrl(f.id)">下载</a>
          <button class="btn btn-sm" :disabled="processing.some(p=>p.id===f.id)" @click="reindex(f)">重索引</button>
          <button class="btn btn-sm danger" :disabled="processing.some(p=>p.id===f.id)" @click="remove(f)">删除</button>
        </div>
      </div>
    </div>

    <div class="pager" v-if="total > pageSize">
      <button class="btn btn-sm" :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span class="page-info">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button class="btn btn-sm" :disabled="page >= Math.ceil(total / pageSize)" @click="page++; load()">下一页</button>
    </div>

    <UploadModal v-if="showUpload" @close="showUpload = false" @uploaded="load" />
  </div>
</template>

<style scoped>
.lib-title { font-size: 26px; letter-spacing: 3px; }
.lib-sub { font-size: 13px; color: var(--ink-faint); margin-top: 4px; }
.lib-head { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 28px; }
.lib-filters { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }
.cats { display: flex; gap: 8px; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--brand-line); background: var(--white); color: var(--ink-soft);
  border-radius: 999px; padding: 5px 15px; font-size: 12.5px; cursor: pointer;
  transition: all 0.2s; font-family: var(--sans); display: inline-flex; align-items: center; gap: 6px;
}
.chip:hover { border-color: var(--brand); }
.chip.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.chip-count { font-size: 11px; opacity: 0.75; }
.lib-search { width: 240px; }

/* 文件网格：宽屏 3-4 列 */
.file-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}
.file-row {
  display: flex; flex-direction: column; align-items: flex-start; gap: 14px;
  padding: 24px; cursor: pointer; position: relative; overflow: hidden;
}
.file-row::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--brand), transparent);
  opacity: 0; transition: opacity 0.25s;
}
.file-row:hover::before { opacity: 1; }
.file-icon {
  width: 52px; height: 52px; border-radius: 12px; flex-shrink: 0;
  background: linear-gradient(135deg, var(--brand), var(--brand-deep)); color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 20px;
  box-shadow: 0 4px 14px var(--glow);
}
.file-info { flex: 1; min-width: 0; width: 100%; }
.file-top { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.file-name { font-family: var(--serif); font-size: 16px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
.file-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.file-tags { font-size: 12px; color: var(--ink-faint); }
.file-detail { font-size: 12px; color: var(--ink-faint); }
.file-error { font-size: 12px; color: var(--danger); margin-top: 6px; }
.file-error.soft { color: var(--brand-deep); }
.progress-line { display: flex; align-items: center; gap: 10px; margin-top: 10px; width: 100%; max-width: 100%; }
.bar { flex: 1; height: 6px; background: var(--bg-deep); border-radius: 3px; overflow: hidden; }
.bar-inner { height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand-deep)); transition: width 0.4s; }
.bar-text { font-size: 11.5px; color: var(--ink-soft); }
.file-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-start; width: 100%; padding-top: 12px; border-top: 1px dashed var(--brand-line); }
.btn.danger:hover { border-color: var(--danger); background: var(--danger); color: #fff; }
.pager { display: flex; justify-content: center; align-items: center; gap: 16px; margin-top: 36px; }
.page-info { font-size: 13px; color: var(--ink-soft); }
.lib-head-actions{display:flex;gap:12px;flex-wrap:wrap}.duplicate-count{font-size:11px;color:var(--brand);white-space:nowrap}@media(max-width:650px){.lib-head{align-items:stretch;flex-direction:column;gap:18px}}
</style>
