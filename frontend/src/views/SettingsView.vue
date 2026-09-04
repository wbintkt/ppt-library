<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type SettingsInfo } from '../api'
import { toast } from '../toast'
import { THEMES, currentTheme, setTheme, type ThemeId } from '../theme'

const info = ref<SettingsInfo | null>(null)
const apiKey = ref('')
const saving = ref(false)

async function load() {
  try {
    info.value = await api.settings()
  } catch (e: any) {
    toast(e.message || '加载失败', 'error')
  }
}

async function save() {
  saving.value = true
  try {
    const resp = await api.saveApiKey(apiKey.value)
    toast(resp.has_api_key ? 'API Key 已保存，可对素材重新索引以启用语义检索' : '已清空 API Key，当前为关键词检索模式')
    apiKey.value = ''
    load()
  } catch (e: any) {
    toast(e.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

function pickTheme(id: ThemeId) {
  setTheme(id)
  toast(`已切换为「${THEMES.find((t) => t.id === id)?.name}」主题`)
}

onMounted(load)
</script>

<template>
  <div class="settings-view" v-if="info">
    <h2 class="set-title fade-up">系统设置</h2>

    <!-- 界面主题 -->
    <section class="card set-card fade-up fade-up-1">
      <div class="set-head">
        <h3>界面主题</h3>
        <span class="badge ready">◆ 即时生效</span>
      </div>
      <p class="set-desc">
        切换整套配色风格（含登录页）。选择后立即生效，并记住在当前浏览器。
      </p>
      <div class="theme-grid">
        <button
          v-for="t in THEMES"
          :key="t.id"
          class="theme-opt"
          :class="{ active: currentTheme === t.id }"
          @click="pickTheme(t.id)"
        >
          <span class="theme-swatches">
            <i v-for="(c, i) in t.swatches" :key="i" :style="{ background: c }"></i>
          </span>
          <span class="theme-meta">
            <span class="theme-name">{{ t.name }}</span>
            <span class="theme-desc">{{ t.desc }}</span>
          </span>
          <span v-if="currentTheme === t.id" class="theme-check">✓</span>
        </button>
      </div>
    </section>

    <!-- 语义检索配置 -->
    <section class="card set-card fade-up fade-up-2">
      <div class="set-head">
        <h3>语义检索引擎</h3>
        <span class="badge" :class="info.vector_mode ? 'ready' : 'ready_limited'">
          {{ info.vector_mode ? '◆ 语义检索已启用' : '◇ 关键词检索模式' }}
        </span>
      </div>
      <p class="set-desc">
        系统通过多模态 Embedding 模型（{{ info.embed_model }}，{{ info.embed_dim }} 维）将页面图片与文字映射到同一向量空间，
        实现「文字 → 图片」的跨模态检索。配置阿里云百炼 API Key 后，新上传素材自动向量化；已有素材需在素材库中「重索引」。
      </p>
      <div class="key-row">
        <input
          v-model="apiKey"
          class="text-input key-input"
          type="password"
          :placeholder="info.has_api_key ? '已配置（输入新 Key 可覆盖，留空保存则清除）' : '输入阿里云百炼 DashScope API Key（sk-...）'"
        />
        <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存' }}</button>
      </div>
      <p class="set-hint">Key 仅保存在本服务器数据库中，不会外传。</p>
    </section>

    <!-- 系统状态 -->
    <section class="card set-card fade-up fade-up-3">
      <div class="set-head"><h3>素材库状态</h3></div>
      <div class="stat-grid">
        <div class="stat"><span class="stat-num">{{ info.total_files }}</span><span class="stat-label">PPT 文件</span></div>
        <div class="stat"><span class="stat-num">{{ info.total_pages }}</span><span class="stat-label">页面素材</span></div>
        <div class="stat"><span class="stat-num">{{ info.indexed_pages }}</span><span class="stat-label">已向量化页面</span></div>
      </div>
    </section>

    <section class="card set-card fade-up">
      <div class="set-head"><h3>使用说明</h3></div>
      <ul class="guide">
        <li>◆ 上传 PPT 后系统自动按页解析，生成页面图片与文本，无需人工处理</li>
        <li>◆ 检索结果以「页」为单位，点击卡片可预览大图、查看文本、下载本页（单页 PPTX，原生可编辑）</li>
        <li>◆ 支持自然语言描述图片内容，如「带无人机和基站关系图的页面」</li>
        <li>◆ 文件 Hash 查重：重复上传的 PPT 不会重复入库</li>
      </ul>
    </section>
  </div>
  <div v-else class="empty-state"><span class="loading-dots">加载中</span></div>
</template>

<style scoped>
.set-title { font-size: 24px; letter-spacing: 2px; margin-bottom: 24px; }
.set-card { padding: 24px 28px; margin-bottom: 20px; }
.set-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.set-head h3 { font-size: 16px; letter-spacing: 1px; }
.set-desc { font-size: 13.5px; color: var(--ink-soft); margin-bottom: 18px; line-height: 1.9; }
.key-row { display: flex; gap: 12px; }
.key-input { flex: 1; max-width: 520px; }
.set-hint { font-size: 12px; color: var(--ink-faint); margin-top: 10px; }
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat { text-align: center; padding: 18px 10px; background: var(--bg); border: 1px solid var(--brand-line); border-radius: 10px; }
.stat-num { display: block; font-family: var(--serif); font-size: 30px; font-weight: 700; color: var(--brand-deep); }
.stat-label { font-size: 12.5px; color: var(--ink-faint); margin-top: 4px; display: block; }
.guide { list-style: none; }
.guide li { font-size: 13.5px; color: var(--ink-soft); padding: 7px 0; border-bottom: 1px dashed var(--brand-line); }
.guide li:last-child { border-bottom: none; }

.theme-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.theme-opt {
  display: flex; align-items: center; gap: 14px; text-align: left;
  padding: 16px 18px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--brand-line); background: var(--white);
  font-family: var(--sans); transition: all 0.2s ease;
}
.theme-opt:hover { border-color: var(--brand); box-shadow: var(--shadow-hover); }
.theme-opt.active { border-color: var(--brand); box-shadow: 0 0 0 1.5px var(--brand); }
.theme-swatches {
  display: flex; flex-direction: column; gap: 5px; padding: 7px;
  border-radius: 8px; background: var(--bg-deep); flex-shrink: 0;
}
.theme-swatches i { display: block; width: 88px; height: 7px; border-radius: 4px; }
.theme-meta { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.theme-name { font-family: var(--serif); font-size: 14.5px; font-weight: 700; color: var(--ink); }
.theme-desc { font-size: 12px; color: var(--ink-faint); line-height: 1.6; }
.theme-check {
  width: 22px; height: 22px; border-radius: 50%; background: var(--brand); color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0;
}
@media (max-width: 720px) { .theme-grid { grid-template-columns: 1fr; } }
</style>
