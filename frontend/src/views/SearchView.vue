<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type PageSummary } from '../api'
import { searchState as state, togglePage, movePage, type SelectedPage } from '../searchState'
import { toast } from '../toast'
import { saveBlob } from '../download'
import AppDialog from '../components/AppDialog.vue'
import PageImage from '../components/PageImage.vue'
import PreviewModal from '../components/PreviewModal.vue'

const route = useRoute()
const router = useRouter()
const routeQuery = computed(() => typeof route.query.q === 'string' ? route.query.q.trim() : '')
const draft = ref(routeQuery.value)
const isHome = computed(() => !routeQuery.value)
const searching = ref(false)
const error = ref('')
const input = ref<HTMLInputElement>()
const preview = ref<SelectedPage | null>(null)
const selectedOpen = ref(false)
const exporting = ref(false)
const selectedIds = computed(() => new Set(state.selected.map(p => p.page_id)))
const canLoadMore = computed(() => state.limit < 50 && state.results.length >= state.limit)
let controller: AbortController | undefined
let requestId = 0

async function runSearch(query: string, limit = 20) {
  controller?.abort()
  const id = ++requestId
  controller = new AbortController()
  searching.value = true
  error.value = ''
  try {
    const response = await api.search(query, '', limit, controller.signal)
    if (id !== requestId) return
    state.results = response.items
    state.query = query
    state.limit = limit
    state.hasResults = true
  } catch (e: any) {
    if (id !== requestId || e.name === 'AbortError') return
    error.value = e.message || '暂时无法完成搜索，请重试。'
  } finally {
    if (id === requestId) searching.value = false
  }
}

watch(routeQuery, (q) => {
  draft.value = q
  controller?.abort()
  requestId++
  searching.value = false
  error.value = ''
  if (q && (state.query !== q || !state.hasResults)) void runSearch(q)
}, { immediate: true })

function guardComposition(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) event.preventDefault()
}
async function submit() {
  const q = draft.value.trim()
  if (!q) { input.value?.focus(); return }
  if (q === routeQuery.value) {
    if (!searching.value) void runSearch(q)
  } else await router.push({ name: 'search', query: { q } })
}

function cancelSearch() {
  controller?.abort()
  requestId++
  searching.value = false
  error.value = ''
  router.replace({ name: 'search', query: state.hasResults ? { q: state.query } : {} })
}
function clearInput() { draft.value = ''; input.value?.focus() }
function toggle(item: SelectedPage) {
  if (!togglePage(item)) toast('一次最多选择 200 页，请先导出已选内容。', 'error')
}
function togglePreview(page: PageSummary) { toggle({ page_id: page.id, page_no: page.page_no, title: page.title }) }
function showPreview(item: SelectedPage) { preview.value = item }
function showSelectedPreview(item: SelectedPage) {
  selectedOpen.value = false
  nextTick(() => { preview.value = item })
}
function formatScore(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? (value * 100).toFixed(1) : null
}
async function exportSelected() {
  if (exporting.value || !state.selected.length) return
  const ids = state.selected.map(p => p.page_id)
  exporting.value = true
  try {
    saveBlob(await api.exportPages(ids), `页面合集_${ids.length}页.pptx`)
    toast(`已导出 ${ids.length} 页，已选内容为你保留。`)
  } catch (e: any) { toast(e.message || '导出失败，请重试。', 'error') }
  finally { exporting.value = false }
}
function focusSearch(event: KeyboardEvent) {
  if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || document.querySelector('dialog[open]')) return
  const target = event.target
  if (target instanceof HTMLElement && target.closest('input, textarea, select, [contenteditable="true"]')) return
  event.preventDefault()
  input.value?.focus()
}
onMounted(() => { document.addEventListener('keydown', focusSearch) })
onBeforeUnmount(() => {
  controller?.abort()
  requestId++
  document.removeEventListener('keydown', focusSearch)
})
</script>

<template>
  <div class="search-view" :class="{ 'home-view': isHome, 'has-selection': state.selected.length }">
    <section v-if="isHome" class="search-hero" aria-labelledby="home-title">
      <svg class="hero-mark" width="68" height="66" viewBox="0 0 68 66" fill="none" aria-hidden="true">
        <path d="M34 6 63 21 34 36 5 21 34 6ZM5 32l29 15 29-15M5 43l29 15 29-15" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
      </svg>
      <h1 id="home-title">找到，恰好那一页</h1>
      <p>让每一份内容，再次发挥价值</p>
    </section>

    <Teleport to="#header-search" :disabled="isHome">
      <form class="search-form" :class="{ 'hero-form': isHome }" role="search" @submit.prevent="submit">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.8" cy="10.8" r="7.1" stroke="currentColor" stroke-width="1.7"/><path d="m16 16 4.5 4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
        <input ref="input" v-model="draft" type="search" aria-label="搜索内容" placeholder="搜索关键词，或描述你需要的内容" maxlength="500" @keydown.enter="guardComposition" autocomplete="off" enterkeyhint="search" />
        <button v-if="draft" type="button" class="clear-search" aria-label="清空搜索词" @click="clearInput">×</button>
        <button class="submit-search" type="submit" :disabled="searching && draft.trim() === routeQuery">
          <span v-if="searching" class="spinner" aria-hidden="true"></span><span>{{ searching ? '搜索中' : '搜索' }}</span>
        </button>
      </form>
    </Teleport>
    <p v-if="isHome" class="search-tip">按 Enter 开始搜索<span class="shortcut-tip"> · 按 / 聚焦搜索框</span></p>

    <section v-if="!isHome" class="results" :aria-busy="searching" aria-labelledby="results-title">
      <div class="results-heading">
        <div>
          <h1 id="results-title">搜索结果</h1>
          <p role="status" aria-live="polite">{{ searching ? '正在寻找相关内容…' : error ? '搜索暂未完成' : state.results.length ? `为你呈现 ${state.results.length} 页相关内容` : '试着换一个关键词' }}</p>
        </div>
        <div class="result-controls">
          <button v-if="searching" class="text-button" @click="cancelSearch">取消搜索</button>
          <template v-else-if="state.results.length && !error">
            <span class="sort-label">按匹配度排序</span>
            <button class="density-toggle" :aria-label="state.compact ? '切换为大图视图' : '切换为紧凑视图'" :aria-pressed="state.compact" :title="state.compact ? '大图视图' : '紧凑视图'" @click="state.compact = !state.compact">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path v-if="!state.compact" d="M3 3h6v6H3zM15 3h6v6h-6zM3 15h6v6H3zM15 15h6v6h-6z"/><path v-else d="M3 3h4v4H3zM10 3h4v4h-4zM17 3h4v4h-4zM3 10h4v4H3zM10 10h4v4h-4zM17 10h4v4h-4zM3 17h4v4H3zM10 17h4v4h-4zM17 17h4v4h-4z"/></svg>
            </button>
          </template>
        </div>
      </div>

      <div v-if="searching" class="result-grid skeleton-grid" :class="{ compact: state.compact }" aria-hidden="true">
        <div v-for="n in 6" :key="n" class="skeleton-card"><div class="skeleton-image"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>
      </div>
      <div v-else-if="error" class="search-empty" role="alert">
        <span class="empty-mark" aria-hidden="true">!</span><h2>连接暂时中断</h2><p>{{ error }}</p>
        <button class="btn primary" @click="runSearch(routeQuery)">重新搜索</button>
      </div>
      <div v-else-if="!state.results.length" class="search-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" aria-hidden="true"><circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/></svg>
        <h2>还没有找到合适的内容</h2><p>试试更简短的关键词，或换一种描述。</p><button class="btn" @click="input?.focus()">修改搜索词</button>
      </div>
      <template v-else>
        <div class="result-grid" :class="{ compact: state.compact }">
          <article v-for="(item, index) in state.results" :key="item.page_id" class="result-card" :class="{ selected: selectedIds.has(item.page_id) }">
            <button class="card-preview" :aria-label="`预览：${item.title}`" @click="showPreview(item)">
              <div class="result-thumbnail"><PageImage :page-id="item.page_id" :title="item.title" :eager="index < 3"/><span class="preview-hint">放大预览 ↗</span></div>
              <div class="result-card-info">
                <div class="result-title"><h2 :title="item.title">{{ item.title }}</h2><p>第 {{ item.page_no }} 页</p></div>
                <div class="match-score" title="匹配度由当前检索引擎计算，用于衡量相关程度，不代表准确率。">
                  <span>匹配度</span><strong v-if="formatScore(item.display_score) !== null">{{ formatScore(item.display_score) }}<small>%</small></strong><strong v-else class="score-unavailable">—</strong>
                </div>
              </div>
            </button>
            <label class="selection-check" :title="selectedIds.has(item.page_id) ? '取消选择' : '选择此页'">
              <input type="checkbox" :aria-label="`选择：${item.title}`" :checked="selectedIds.has(item.page_id)" @change="toggle(item)" />
              <span class="check-visual" aria-hidden="true"><svg viewBox="0 0 20 20" fill="none"><path d="m4 10 4 4 8-9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
            </label>
          </article>
        </div>
        <div class="results-end">
          <button v-if="canLoadMore" class="btn" @click="runSearch(routeQuery, 50)">查看更多相关页面</button>
          <span v-else>以上为本次搜索的相关内容</span>
        </div>
      </template>
    </section>

    <Transition name="selection-bar">
      <aside v-if="state.selected.length" class="selection-bar" aria-label="已选页面操作">
        <div class="selection-bar-inner">
          <span class="selection-count" aria-live="polite">已选 <b>{{ state.selected.length }}</b> 页</span>
          <button class="text-button clear-selection" :disabled="exporting" @click="state.selected = []">清空</button>
          <div class="selection-actions"><button class="btn" @click="selectedOpen = true">查看已选</button><button class="btn primary" :disabled="exporting" @click="exportSelected"><span v-if="exporting" class="spinner" aria-hidden="true"></span>{{ exporting ? '正在生成…' : '导出 PPT' }}</button></div>
        </div>
      </aside>
    </Transition>

    <AppDialog v-if="selectedOpen" title="已选页面" @close="selectedOpen = false">
      <p class="selection-intro">按下列顺序导出。你可以调整顺序，或继续搜索添加页面。</p>
      <ol v-if="state.selected.length" class="selected-list">
        <li v-for="(item, index) in state.selected" :key="item.page_id">
          <span class="selection-index">{{ index + 1 }}</span>
          <button class="selected-thumbnail" :aria-label="`预览已选：${item.title}`" @click="showSelectedPreview(item)"><PageImage :page-id="item.page_id" :title="item.title" /></button>
          <div class="selected-title"><strong>{{ item.title }}</strong><span>第 {{ item.page_no }} 页</span></div>
          <div class="reorder-actions"><button class="icon-button" :aria-label="`上移：${item.title}`" :disabled="index === 0 || exporting" @click="movePage(index, -1)">↑</button><button class="icon-button" :aria-label="`下移：${item.title}`" :disabled="index === state.selected.length - 1 || exporting" @click="movePage(index, 1)">↓</button><button class="icon-button" :aria-label="`移除：${item.title}`" :disabled="exporting" @click="toggle(item)">×</button></div>
        </li>
      </ol>
      <p v-else class="selection-intro">还没有选中的页面，去搜索结果中勾选吧。</p>
      <template #footer><button class="btn" @click="selectedOpen = false">继续挑选</button><button class="btn primary" :disabled="exporting || !state.selected.length" @click="exportSelected">{{ exporting ? '正在生成…' : `导出 ${state.selected.length} 页` }}</button></template>
    </AppDialog>
    <PreviewModal v-if="preview" :page-id="preview.page_id" :title="preview.title" :page-ids="state.results.map(p => p.page_id)" :selected-ids="[...selectedIds]" @toggle="togglePreview" @close="preview = null" />
  </div>
</template>

<style scoped>
.search-view { --brand: #c6372d; --brand-deep: #a72c24; --brand-soft: #fcf3f0; }
.home-view { max-width: 820px; margin: 0 auto; padding-top: clamp(64px, 13vh, 150px); text-align: center; }
.search-hero { margin-bottom: 44px; }
.hero-mark { color: var(--brand); margin-bottom: 26px; }
.search-hero h1 { font-size: clamp(30px, 4vw, 52px); font-weight: 400; letter-spacing: .065em; line-height: 1.4; }
.search-hero p { font-family: var(--serif); font-size: 18px; letter-spacing: .13em; color: var(--ink-soft); margin-top: 20px; }
.search-form { display: flex; align-items: center; gap: 14px; padding: 6px 6px 6px 18px; width: 100%; background: #fff; border: 1px solid #d8d4cf; border-radius: 6px; transition: border-color .18s, box-shadow .18s; color: #47433f; --brand: #c6372d; --brand-deep: #a72c24; }
.search-form:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px #c6372d0b; }
.search-form > svg { flex-shrink: 0; }
.search-form input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--ink); font: inherit; font-size: 15px; height: 36px; }
.search-form input:focus-visible { outline: none; }
.search-form input::placeholder { color: #8a8580; }
.search-form input::-webkit-search-cancel-button { display: none; }
.submit-search { min-width: 88px; height: 40px; border: 0; border-radius: 4px; background: var(--brand); color: #fff; display: flex; gap: 7px; align-items: center; justify-content: center; font: inherit; cursor: pointer; }
.submit-search:hover:not(:disabled) { background: var(--brand-deep); }
.submit-search:disabled { opacity: .65; cursor: default; }
.clear-search { background: none; border: 0; color: var(--ink-soft); font: 22px var(--sans); width: 30px; height: 36px; cursor: pointer; }
.hero-form { max-width: 760px; margin: auto; padding: 8px 8px 8px 22px; }
.hero-form input { height: 44px; font-size: 16px; }
.hero-form .submit-search { height: 46px; min-width: 100px; font-size: 16px; letter-spacing: .1em; }
.search-tip { margin-top: 20px; font-size: 12px; color: var(--ink-faint); letter-spacing: .04em; }
.shortcut-tip { color: var(--ink-faint); }
.results-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 28px; }
.results-heading h1 { font-size: 32px; font-weight: 400; letter-spacing: .1em; }
.results-heading p { color: var(--ink-soft); font-size: 13px; margin-top: 6px; }
.result-controls { display: flex; align-items: center; gap: 24px; color: var(--ink-soft); }
.sort-label { font-size: 13px; }
.density-toggle { border: 0; background: none; color: var(--ink); display: grid; place-items: center; width: 40px; height: 40px; border-radius: 5px; cursor: pointer; }
.density-toggle:hover, .density-toggle[aria-pressed='true'] { background: var(--bg-deep); }
.result-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; }
.result-grid.compact { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; }
.result-card { position: relative; min-width: 0; border: 1px solid var(--line); border-radius: 6px; background: #fff; transition: border-color .18s, box-shadow .18s; }
.result-card:hover { border-color: #b9b2aa; box-shadow: 0 4px 16px #24232109; }
.result-card.selected { border-color: var(--brand); box-shadow: 0 0 0 .5px var(--brand); }
.card-preview { display: block; width: 100%; padding: 0; text-align: left; background: none; border: 0; border-radius: 6px; color: inherit; font: inherit; cursor: pointer; overflow: hidden; }
.result-thumbnail { position: relative; aspect-ratio: 16/9; border-bottom: 1px solid var(--line); }
.preview-hint { position: absolute; right: 12px; bottom: 12px; font-size: 12px; background: #fff; color: var(--ink); padding: 4px 10px; border: 1px solid var(--line); border-radius: 4px; opacity: 0; transition: opacity .18s; }
.card-preview:hover .preview-hint, .card-preview:focus-visible .preview-hint { opacity: 1; }
.result-card-info { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px; min-height: 88px; }
.selected .result-card-info { background: var(--brand-soft); }
.result-title { min-width: 0; }
.result-title h2 { font-family: var(--sans); font-size: 15px; font-weight: 500; line-height: 1.5; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; }
.result-title p { font-size: 12px; color: var(--ink-soft); margin-top: 5px; }
.match-score { flex-shrink: 0; text-align: right; }
.match-score > span { display: block; font-size: 11px; color: var(--ink-soft); }
.match-score strong { display: block; font-size: 25px; font-weight: 500; color: var(--brand); font-variant-numeric: tabular-nums; line-height: 1.35; letter-spacing: -.04em; }
.match-score small { font-size: 14px; margin-left: 2px; }
.match-score .score-unavailable { color: var(--ink-faint); }
.selection-check { position: absolute; top: 8px; left: 8px; width: 44px; height: 44px; display: grid; place-items: center; border-radius: 5px; background: #fffffff5; cursor: pointer; }
.selection-check input { position: absolute; opacity: 0; width: 100%; height: 100%; inset: 0; margin: 0; cursor: pointer; }
.check-visual { display: grid; place-items: center; width: 28px; height: 28px; border: 1.8px solid #625b54; border-radius: 4px; color: transparent; background: white; pointer-events: none; }
.check-visual svg { width: 22px; height: 22px; }
.selection-check input:checked + .check-visual { background: var(--brand); border-color: var(--brand); color: white; }
.selection-check input:focus-visible + .check-visual { outline: 2px solid var(--brand); outline-offset: 3px; }
.selection-check:hover .check-visual { border-color: var(--brand); }
.results-end { text-align: center; padding: 36px 0 0; color: var(--ink-faint); font-size: 12px; }
.search-empty { min-height: 360px; padding: 80px 20px; text-align: center; color: var(--ink-soft); }
.search-empty > svg { margin-bottom: 20px; color: #b2aaa1; }
.search-empty h2 { font-size: 23px; font-weight: 400; color: var(--ink); }
.search-empty p { margin: 12px 0 24px; font-size: 14px; }
.empty-mark { display: inline-grid; place-items: center; border: 1px solid var(--brand); border-radius: 50%; width: 36px; height: 36px; color: var(--brand); margin-bottom: 18px; }
.skeleton-card { border: 1px solid var(--line); border-radius: 6px; overflow: hidden; background: #fff; padding-bottom: 20px; }
.skeleton-image { aspect-ratio: 16/9; background: var(--bg-deep); animation: breathe 1.6s ease-in-out infinite alternate; }
.skeleton-line { margin: 20px 18px 0; height: 12px; width: 65%; background: var(--bg-deep); border-radius: 2px; }
.skeleton-line.short { margin-top: 12px; width: 25%; height: 8px; }
@keyframes breathe { to { opacity: .4; } }
.has-selection { padding-bottom: 74px; }
.selection-bar { position: fixed; bottom: 0; left: 0; right: 0; z-index: 60; background: #fff; border-top: 1px solid var(--line); padding: 14px max(24px, calc((100vw - 1400px) / 2)); padding-bottom: max(14px, env(safe-area-inset-bottom)); }
.selection-bar-inner { display: flex; align-items: center; gap: 28px; }
.selection-count { font-size: 14px; white-space: nowrap; }
.selection-count b { font-size: 23px; font-weight: 500; color: var(--brand); padding: 0 7px; font-variant-numeric: tabular-nums; }
.selection-actions { margin-left: auto; display: flex; gap: 14px; }
.selection-actions .btn { min-width: 116px; justify-content: center; }
.selection-bar-enter-active, .selection-bar-leave-active { transition: transform .2s ease, opacity .2s ease; }
.selection-bar-enter-from, .selection-bar-leave-to { transform: translateY(12px); opacity: 0; }
.selection-intro { font-size: 13px; color: var(--ink-soft); padding: 20px 24px; }
.selected-list { list-style: none; padding: 0 24px 20px; }
.selected-list li { display: flex; align-items: center; gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--line); }
.selection-index { font-size: 12px; color: var(--ink-faint); min-width: 16px; }
.selected-thumbnail { width: 92px; aspect-ratio: 16/9; border: 1px solid var(--line); border-radius: 3px; padding: 0; cursor: pointer; overflow: hidden; flex-shrink: 0; }
.selected-title { flex: 1; min-width: 0; }
.selected-title strong { font-size: 13px; font-weight: 500; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-title span { color: var(--ink-soft); font-size: 12px; }
.reorder-actions { display: flex; gap: 2px; }
@media (max-width: 1100px) { .result-grid.compact { grid-template-columns: repeat(3, minmax(0,1fr)); } .result-card-info { padding: 14px; } .match-score strong { font-size: 22px; } }
@media (max-width: 900px) { .result-grid, .result-grid.compact { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px; } .density-toggle { display: none; } .home-view { padding-top: 12vh; } }
@media (max-width: 600px) {
  .home-view { padding-top: 10vh; } .hero-mark { width: 50px; height: 50px; margin-bottom: 24px; } .search-hero { margin-bottom: 30px; } .search-hero h1 { letter-spacing: .025em; } .search-hero p { font-size: 14px; letter-spacing: .04em; margin-top: 16px; }
  .search-form, .hero-form { padding: 5px 5px 5px 12px; gap: 8px; } .search-form input, .hero-form input { font-size: 14px; height: 40px; } .hero-form .submit-search, .submit-search { min-width: 64px; height: 40px; font-size: 14px; } .clear-search { width: 22px; } .shortcut-tip { display: none; }
  .results-heading { margin-bottom: 22px; gap: 12px; } .results-heading h1 { font-size: 26px; } .sort-label { font-size: 11px; } .result-grid, .result-grid.compact { grid-template-columns: 1fr; gap: 20px; } .result-card-info { min-height: 82px; padding: 14px 16px; } .result-title h2 { font-size: 16px; } .match-score strong { font-size: 25px; }
  .selection-bar { padding-left: 16px; padding-right: 16px; } .selection-bar-inner { gap: 12px; } .selection-actions { gap: 8px; } .selection-actions .btn { min-width: 0; padding: 9px 12px; font-size: 12px; } .selection-count { font-size: 12px; } .selection-count b { padding: 0 3px; font-size: 20px; } .clear-selection { font-size: 12px; }
  .selected-list { padding: 0 16px 16px; } .selected-list li { gap: 8px; } .selected-thumbnail { width: 60px; } .reorder-actions { flex-wrap: wrap; max-width: 72px; } .selection-index { display: none; }
}
</style>
