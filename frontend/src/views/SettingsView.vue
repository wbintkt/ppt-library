<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type SettingsInfo } from '../api'
import { toast } from '../toast'

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

onMounted(load)
</script>

<template>
  <div class="settings-view" v-if="info">
    <h2 class="set-title fade-up">系统设置</h2>

    <!-- 语义检索配置 -->
    <section class="card set-card fade-up fade-up-1">
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
    <section class="card set-card fade-up fade-up-2">
      <div class="set-head"><h3>素材库状态</h3></div>
      <div class="stat-grid">
        <div class="stat"><span class="stat-num">{{ info.total_files }}</span><span class="stat-label">PPT 文件</span></div>
        <div class="stat"><span class="stat-num">{{ info.total_pages }}</span><span class="stat-label">页面素材</span></div>
        <div class="stat"><span class="stat-num">{{ info.indexed_pages }}</span><span class="stat-label">已向量化页面</span></div>
      </div>
    </section>

    <section class="card set-card fade-up fade-up-3">
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
</style>
