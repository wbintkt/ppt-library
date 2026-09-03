<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, imageUrl, type FileSummary, type PageSummary } from '../api'
import { toast } from '../toast'
import PreviewModal from '../components/PreviewModal.vue'

const route = useRoute()
const router = useRouter()
const fileId = Number(route.params.id)

const file = ref<FileSummary | null>(null)
const pages = ref<PageSummary[]>([])
const total = ref(0)
const pageNo = ref(1)
const pageSize = 24
const editing = ref(false)
const editName = ref('')
const editCategory = ref('')
const editTags = ref('')
const editSource = ref('')
const preview = ref<{ pageId: number; title: string } | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const loading = computed(() => !file.value)

async function loadFile() {
  try {
    file.value = await api.getFile(fileId)
    editName.value = file.value.name
    editCategory.value = file.value.category
    editTags.value = file.value.tags
    editSource.value = file.value.source
  } catch (e: any) {
    toast(e.message || '加载失败', 'error')
  }
}

async function loadPages() {
  try {
    const resp = await api.listPages({ file_id: fileId, page: pageNo.value, page_size: pageSize })
    pages.value = resp.items
    total.value = resp.total
  } catch { /* ignore */ }
}

async function refresh() {
  if (file.value && (file.value.status === 'parsing' || file.value.status === 'embedding')) {
    await loadFile()
  }
}

async function saveEdit() {
  try {
    file.value = await api.updateFile(fileId, {
      name: editName.value, category: editCategory.value, tags: editTags.value, source: editSource.value,
    })
    editing.value = false
    toast('已保存')
  } catch (e: any) {
    toast(e.message || '保存失败', 'error')
  }
}

function remove() {
  if (!confirm(`确认删除「${file.value?.name}」？`)) return
  api.deleteFile(fileId).then(() => {
    toast('已删除')
    router.push('/library')
  }).catch((e: any) => toast(e.message || '删除失败', 'error'))
}

onMounted(() => {
  loadFile()
  loadPages()
  timer = setInterval(refresh, 6000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="detail-view" v-if="file">
    <button class="back-link" @click="router.push('/library')">← 返回素材库</button>

    <div class="detail-head fade-up">
      <div class="head-info">
        <h2 class="detail-title">{{ file.name }}</h2>
        <div class="detail-meta">
          <span class="badge" :class="file.status">{{ file.status === 'ready' ? '已完成' : file.status === 'ready_limited' ? '可检索*' : file.status === 'parsing' ? '解析中' : file.status === 'embedding' ? '向量化中' : '失败' }}</span>
          <span class="tag">{{ file.category }}</span>
          <span class="meta-text">{{ file.page_count }} 页</span>
          <span class="meta-text">{{ (file.file_size / 1024 / 1024).toFixed(2) }} MB</span>
          <span class="meta-text" v-if="file.source">来源：{{ file.source }}</span>
          <span class="meta-text" v-if="file.tags">标签：{{ file.tags }}</span>
        </div>
        <p class="file-error" v-if="file.error_message">{{ file.error_message }}</p>
      </div>
      <div class="head-actions">
        <button class="btn btn-sm" @click="editing = !editing">{{ editing ? '取消' : '编辑信息' }}</button>
        <a class="btn btn-sm primary" :href="api.downloadUrl(file.id)">下载原文件</a>
        <button class="btn btn-sm danger" @click="remove">删除</button>
      </div>
    </div>

    <div class="edit-panel card" v-if="editing">
      <div class="edit-grid">
        <div class="field"><label>文件名</label><input v-model="editName" class="text-input" /></div>
        <div class="field"><label>分类</label><input v-model="editCategory" class="text-input" /></div>
        <div class="field"><label>来源</label><input v-model="editSource" class="text-input" /></div>
        <div class="field"><label>标签</label><input v-model="editTags" class="text-input" placeholder="逗号分隔" /></div>
      </div>
      <div class="edit-actions"><button class="btn primary btn-sm" @click="saveEdit">保存</button></div>
    </div>

    <div class="pages-section fade-up fade-up-1">
      <h3 class="pages-title">页面素材 <span class="pages-count">共 {{ total }} 页</span></h3>
      <div class="page-grid">
        <div v-for="p in pages" :key="p.id" class="page-item" @click="preview = { pageId: p.id, title: `${file.name} · 第 ${p.page_no} 页` }">
          <div class="page-thumb">
            <img :src="imageUrl(p.id)" loading="lazy" :alt="p.title" />
            <span class="pno">P{{ p.page_no }}</span>
            <span class="est" :class="p.embedding_status" :title="p.embedding_status === 'done' ? '已向量化' : p.embedding_status === 'failed' ? '向量化失败' : '待向量化'">
              {{ p.embedding_status === 'done' ? '◆' : p.embedding_status === 'failed' ? '×' : '·' }}
            </span>
          </div>
          <p class="ptitle">{{ p.title || `第 ${p.page_no} 页` }}</p>
        </div>
      </div>
      <div class="pager" v-if="total > pageSize">
        <button class="btn btn-sm" :disabled="pageNo <= 1" @click="pageNo--; loadPages()">上一页</button>
        <span class="page-info">{{ pageNo }} / {{ Math.ceil(total / pageSize) }}</span>
        <button class="btn btn-sm" :disabled="pageNo >= Math.ceil(total / pageSize)" @click="pageNo++; loadPages()">下一页</button>
      </div>
    </div>

    <PreviewModal v-if="preview" :page-id="preview.pageId" :title="preview.title" @close="preview = null" />
  </div>
  <div v-else class="empty-state"><span class="loading-dots">加载中</span></div>
</template>

<style scoped>
.back-link { border: none; background: none; color: var(--ink-soft); cursor: pointer; font-size: 13px; padding: 0; margin-bottom: 18px; font-family: var(--sans); }
.back-link:hover { color: var(--brand-deep); }
.detail-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 24px; }
.detail-title { font-size: 22px; letter-spacing: 1px; word-break: break-all; }
.detail-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.meta-text { font-size: 12.5px; color: var(--ink-faint); }
.file-error { font-size: 12.5px; color: var(--danger); margin-top: 8px; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.btn.danger:hover { border-color: var(--danger); background: var(--danger); color: #fff; }

.edit-panel { padding: 18px 22px; margin-bottom: 26px; }
.edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 12.5px; color: var(--ink-soft); }
.edit-actions { margin-top: 14px; text-align: right; }

.pages-title { font-size: 18px; margin-bottom: 20px; letter-spacing: 2px; }
.pages-count { font-size: 12.5px; color: var(--ink-faint); margin-left: 6px; font-family: var(--sans); }
.page-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(224px, 1fr)); gap: 22px; }
.page-item { cursor: pointer; transition: all 0.2s; }
.page-item:hover .page-thumb { box-shadow: var(--shadow-hover); transform: translateY(-3px); }
.page-thumb { position: relative; background: var(--white); border: 1px solid var(--brand-line); border-radius: 12px; overflow: hidden; aspect-ratio: 16/10; transition: all 0.25s; box-shadow: var(--shadow); }
.page-thumb img { width: 100%; height: 100%; object-fit: contain; }
.pno { position: absolute; left: 8px; bottom: 8px; background: rgba(45,42,38,0.72); color: #f3ece2; font-size: 10.5px; padding: 1px 8px; border-radius: 999px; }
.est { position: absolute; right: 8px; top: 8px; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; background: rgba(255,255,255,0.92); border: 1px solid var(--brand-line); color: var(--ink-faint); }
.est.done { color: var(--ok); border-color: var(--ok); }
.est.failed { color: var(--danger); border-color: var(--danger); }
.ptitle { font-size: 12.5px; color: var(--ink-soft); margin-top: 7px; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pager { display: flex; justify-content: center; align-items: center; gap: 16px; margin-top: 26px; }
.page-info { font-size: 13px; color: var(--ink-soft); }
</style>
