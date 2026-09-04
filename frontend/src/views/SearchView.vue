<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, imageUrl, type SearchItem } from '../api'
import { toast } from '../toast'
import PreviewModal from '../components/PreviewModal.vue'

const query = ref('')
const category = ref('')
const categories = ref<{ category: string; count: number }[]>([])
const results = ref<SearchItem[]>([])
const searching = ref(false)
const searched = ref(false)
const mode = ref<'vector' | 'fulltext'>('fulltext')
const total = ref(0)

const previewPage = ref<{ pageId: number; title: string } | null>(null)
const selected = ref<Set<number>>(new Set())
const exporting = ref(false)
const suggestions = [
  '找一页介绍低空通信覆盖能力的 PPT',
  '找带无人机和基站关系图的页面',
  '找一页适合向领导介绍低空安全体系的材料',
  '铁塔站址 资源利用',
  '低空经济 基础设施建设',
]

function toggleSelect(item: SearchItem) {
  const s = new Set(selected.value)
  if (s.has(item.page_id)) s.delete(item.page_id)
  else s.add(item.page_id)
  selected.value = s
}

function clearSelected() {
  selected.value = new Set()
}

async function downloadSelected() {
  const ids = [...selected.value]
  if (!ids.length) return
  exporting.value = true
  try {
    const blob = await api.exportPages(ids)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `页面合集_${ids.length}页.pptx`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast(`已导出 ${ids.length} 页为一份 PPTX`)
  } catch (e: any) {
    toast(e.message || '导出失败', 'error')
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  try {
    categories.value = await api.categories()
  } catch { /* ignore */ }
})

async function doSearch(kw?: string) {
  const q = (kw ?? query.value).trim()
  if (!q) { toast('请输入检索内容', 'error'); return }
  query.value = q
  searching.value = true
  try {
    const resp = await api.search(q, category.value)
    results.value = resp.items
    total.value = resp.total
    searched.value = true
    mode.value = results.value.length && 'embedding_status' in results.value[0] && results.value[0].embedding_status === 'done' ? 'vector' : 'fulltext'
  } catch (e: any) {
    toast(e.message || '检索失败', 'error')
  } finally {
    searching.value = false
  }
}

function openPreview(item: SearchItem) {
  previewPage.value = { pageId: item.page_id, title: `${item.file_name} · 第 ${item.page_no} 页` }
}

function fmtScore(s: number | null | undefined) {
  // 显示纯向量相似度（0-1）；无则不显示
  if (typeof s === 'number' && s > 0 && s <= 1) return `${(s * 100).toFixed(1)}%`
  return ''
}
</script>

<template>
  <div class="search-view">
    <!-- 搜索区 -->
    <section class="hero" :class="{ compact: searched }">
      <div class="hero-inner">
        <h1 class="hero-title">用一句话，找到那一页</h1>
        <p class="hero-sub">自然语言跨模态检索 · 支持描述图片 / 图表 / 版式语义</p>
        <form class="search-box" @submit.prevent="doSearch()">
          <input
            v-model="query"
            class="search-input"
            placeholder="例：找一页介绍低空通信覆盖能力的 PPT"
            @keyup.enter="doSearch()"
          />
          <select v-model="category" class="cat-select">
            <option value="">全部分类</option>
            <option v-for="c in categories" :key="c.category" :value="c.category">{{ c.category }} ({{ c.count }})</option>
          </select>
          <button class="btn primary search-btn" :disabled="searching" type="submit">
            {{ searching ? '检索中' : '检 索' }}
          </button>
        </form>
        <div class="suggest" v-if="!searched">
          <span class="suggest-label">试一试</span>
          <button v-for="s in suggestions" :key="s" class="suggest-item" @click="doSearch(s)">{{ s }}</button>
        </div>
      </div>
    </section>

    <!-- 结果区 -->
    <section v-if="searching" class="result-hint"><span class="loading-dots">正在语义检索</span></section>
    <section v-else-if="searched && results.length === 0" class="empty-state fade-up">
      <span class="icon">◇</span>
      <p>没有找到匹配的页面</p>
      <p class="hint">换个说法试试，或减少筛选条件</p>
    </section>
    <section v-else-if="results.length" class="results">
      <div class="result-meta fade-up">
        <span>共 <b>{{ total }}</b> 页匹配</span>
        <span class="mode-tag">{{ mode === 'vector' ? '◆ 语义向量检索' : '◇ 关键词检索（配置 API Key 后升级语义检索）' }}</span>
      </div>
      <div class="grid">
        <div
          v-for="(item, i) in results"
          :key="item.page_id"
          class="card page-card fade-up"
          :class="['fade-up-' + ((i % 3) + 1), { 'is-selected': selected.has(item.page_id) }]"
          @click="openPreview(item)"
        >
          <div class="thumb-wrap">
            <label class="check-box" :class="{ checked: selected.has(item.page_id) }" @click.stop.prevent="toggleSelect(item)">
              <input type="checkbox" :checked="selected.has(item.page_id)" />
              <span class="check-mark">✓</span>
            </label>
            <img :src="imageUrl(item.page_id)" loading="lazy" :alt="item.title" class="thumb" />
            <span class="page-no">P{{ item.page_no }}</span>
            <span class="score" v-if="item.display_score && item.display_score > 0 && item.display_score <= 1">{{ fmtScore(item.display_score) }}</span>
          </div>
          <div class="card-body">
            <h3 class="card-title">{{ item.title }}</h3>
            <p class="card-text">{{ (item.text || '').slice(0, 90) || '（本页无可提取文本）' }}</p>
            <div class="card-meta">
              <span class="file-name">◆ {{ item.file_name }}</span>
              <span class="tag" v-if="item.category">{{ item.category }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 底部选择操作栏 -->
    <transition name="slide-up">
      <div class="select-bar" v-if="selected.size > 0">
        <span class="select-count">已选 <b>{{ selected.size }}</b> 页</span>
        <button class="btn ghost" @click="clearSelected">清空</button>
        <button class="btn primary" :disabled="exporting" @click="downloadSelected">
          {{ exporting ? '生成中…' : '下载合并 PPTX' }}
        </button>
      </div>
    </transition>

    <PreviewModal
      v-if="previewPage"
      :page-id="previewPage.pageId"
      :title="previewPage.title"
      @close="previewPage = null"
    />
  </div>
</template>

<style scoped>
.hero { text-align: center; padding: 56px 0 12px; transition: all 0.3s; }
.hero.compact { padding: 20px 0 36px; }
.hero.compact .hero-title { font-size: 24px; }
.hero.compact .hero-sub { display: none; }
.hero-title { font-size: 34px; letter-spacing: 6px; margin-bottom: 12px; }
.hero-sub { color: var(--ink-faint); font-size: 13px; letter-spacing: 2px; margin-bottom: 36px; }

.search-box {
  display: flex; gap: 10px; max-width: 860px; margin: 0 auto;
  background: var(--white); border: 1px solid var(--brand-line); border-radius: 999px;
  padding: 8px 8px 8px 26px; box-shadow: var(--shadow);
  transition: box-shadow 0.25s ease;
}
.search-box:focus-within { box-shadow: 0 4px 24px rgba(230, 0, 18, 0.15); border-color: var(--brand); }
.search-input {
  flex: 1; border: none; outline: none; background: transparent;
  font-size: 15px; font-family: var(--sans); color: var(--ink);
}
.cat-select {
  border: none; outline: none; background: var(--bg-deep); color: var(--ink-soft);
  border-radius: 999px; padding: 0 14px; font-size: 12.5px; cursor: pointer; max-width: 150px;
}
.search-btn { border-radius: 999px; padding: 9px 26px; }

.suggest { margin-top: 20px; display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; align-items: center; }
.suggest-label { font-size: 12px; color: var(--ink-faint); margin-right: 4px; }
.suggest-item {
  border: 1px dashed var(--brand-line); background: transparent; color: var(--ink-soft);
  border-radius: 999px; padding: 4px 14px; font-size: 12.5px; cursor: pointer;
  transition: all 0.2s; font-family: var(--sans);
}
.suggest-item:hover { border-color: var(--brand); color: var(--brand-deep); background: #fdf9f2; }

.result-hint { text-align: center; padding: 60px; color: var(--ink-faint); font-size: 14px; }
.result-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; color: var(--ink-soft); font-size: 13px; padding: 0 4px; }
.mode-tag { font-size: 12px; color: var(--ink-faint); }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(264px, 1fr));
  gap: 28px;
}
.page-card { cursor: pointer; overflow: hidden; transition: box-shadow 0.25s, transform 0.25s; }
.page-card.is-selected { box-shadow: 0 0 0 2px var(--brand), var(--shadow); transform: translateY(-2px); }
.check-box {
  position: absolute; top: 10px; left: 10px; z-index: 3;
  width: 22px; height: 22px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.92); border: 1.5px solid var(--brand);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: all 0.2s; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
}
.check-box input { display: none; }
.check-mark { font-size: 13px; color: transparent; font-weight: 700; line-height: 1; transition: color 0.2s; }
.check-box.checked { background: var(--brand); }
.check-box.checked .check-mark { color: #fff; }
.check-box:hover { transform: scale(1.1); }
.thumb-wrap { position: relative; background: var(--bg-deep); aspect-ratio: 16 / 10; overflow: hidden; border-bottom: 1px solid var(--brand-line); }
.thumb { width: 100%; height: 100%; object-fit: contain; transition: transform 0.35s ease; }
.page-card:hover .thumb { transform: scale(1.04); }
.page-no {
  position: absolute; left: 10px; bottom: 10px;
  background: rgba(45, 42, 38, 0.72); color: #f3ece2; font-size: 11px;
  padding: 2px 9px; border-radius: 999px; letter-spacing: 1px;
}
.score {
  position: absolute; right: 10px; top: 10px;
  background: var(--brand); color: #fff; font-size: 11px; font-weight: 700;
  padding: 2px 9px; border-radius: 999px;
}
.card-body { padding: 16px 18px 14px; }
.card-title { font-size: 15px; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-text { font-size: 12.5px; color: var(--ink-soft); height: 2.6em; overflow: hidden; margin-bottom: 10px; line-height: 1.65; }
.card-meta { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.file-name { font-size: 11.5px; color: var(--ink-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 底部选择操作栏 */
.select-bar {
  position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
  display: flex; align-items: center; gap: 14px;
  background: var(--glass-strong); backdrop-filter: blur(6px);
  border: 1px solid var(--brand-line); border-radius: 999px;
  padding: 10px 12px 10px 22px; box-shadow: 0 8px 30px rgba(45, 42, 38, 0.18);
  z-index: 50;
}
.select-count { font-size: 13.5px; color: var(--ink-soft); }
.select-count b { color: var(--brand-deep); font-size: 15px; }
.btn.ghost {
  background: transparent; border: 1px solid var(--brand-line); color: var(--ink-soft);
  border-radius: 999px; padding: 7px 16px; font-size: 12.5px; cursor: pointer;
  transition: all 0.2s; font-family: var(--sans);
}
.btn.ghost:hover { border-color: var(--brand); color: var(--brand-deep); }
.select-bar .btn.primary { border-radius: 999px; padding: 8px 22px; }

.slide-up-enter-active, .slide-up-leave-active { transition: all 0.25s ease; }
.slide-up-enter-from, .slide-up-leave-to { opacity: 0; transform: translateX(-50%) translateY(16px); }
</style>
