<script setup lang="ts">
import { ref } from 'vue'
import { api, type FileSummary } from '../api'
import { toast } from '../toast'

const emit = defineEmits<{ (e: 'close'): void; (e: 'uploaded', file: FileSummary): void }>()

const file = ref<File | null>(null)
const category = ref('未分类')
const tags = ref('')
const source = ref('')
const progress = ref(0)
const uploading = ref(false)
const dragging = ref(false)

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) file.value = input.files[0]
}

function onDrop(e: DragEvent) {
  dragging.value = false
  if (e.dataTransfer?.files.length) file.value = e.dataTransfer.files[0]
}

async function doUpload() {
  if (!file.value) { toast('请选择 PPT 文件', 'error'); return }
  if (!/\.(ppt|pptx)$/i.test(file.value.name)) { toast('仅支持 .ppt / .pptx 文件', 'error'); return }
  uploading.value = true
  progress.value = 0
  try {
    const resp = await api.upload(file.value, category.value, tags.value, source.value, (p) => { progress.value = p })
    toast(`已上传「${resp.name}」，正在后台解析`)
    emit('uploaded', resp)
    emit('close')
  } catch (e: any) {
    toast(e.message || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal upload-modal">
      <div class="modal-head">
        <span class="modal-title">上传 PPT</span>
        <button class="modal-close" @click="emit('close')">×</button>
      </div>
      <div class="modal-body">
        <div
          class="dropzone"
          :class="{ dragging }"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
          @click="($refs.finput as HTMLInputElement)?.click()"
        >
          <input ref="finput" type="file" accept=".ppt,.pptx" hidden @change="onPick" />
          <span class="dz-icon">◆</span>
          <p class="dz-main">{{ file ? file.name : '点击选择或将 PPT 拖拽到此处' }}</p>
          <p class="dz-sub" v-if="file">{{ (file.size / 1024 / 1024).toFixed(2) }} MB</p>
          <p class="dz-sub" v-else>支持 .ppt / .pptx · 上传后自动解析为逐页素材</p>
        </div>

        <div class="form-row">
          <div class="field">
            <label>分类</label>
            <input v-model="category" class="text-input" placeholder="如：低空经济" />
          </div>
          <div class="field">
            <label>来源</label>
            <input v-model="source" class="text-input" placeholder="如：部门汇报 / 外部材料" />
          </div>
        </div>
        <div class="form-row">
          <div class="field wide">
            <label>标签（逗号分隔）</label>
            <input v-model="tags" class="text-input" placeholder="如：通信覆盖,无人机,方案" />
          </div>
        </div>

        <div class="progress-row" v-if="uploading">
          <div class="bar"><div class="bar-inner" :style="{ width: progress + '%' }"></div></div>
          <span class="bar-text">{{ progress }}%</span>
        </div>

        <div class="upload-actions">
          <button class="btn primary" :disabled="uploading" @click="doUpload">{{ uploading ? '上传中...' : '上传并解析' }}</button>
          <button class="btn" @click="emit('close')">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-modal { max-width: 560px; }
.dropzone {
  border: 1.5px dashed var(--brand); border-radius: 12px; padding: 34px 20px;
  text-align: center; cursor: pointer; transition: all 0.25s; background: var(--drop-bg);
  margin-bottom: 20px;
}
.dropzone:hover, .dropzone.dragging { background: var(--drop-hover); border-color: var(--brand-deep); }
.dz-icon { color: var(--brand); font-size: 22px; display: block; margin-bottom: 10px; }
.dz-main { font-size: 14.5px; font-family: var(--serif); color: var(--ink); }
.dz-sub { font-size: 12px; color: var(--ink-faint); margin-top: 6px; }
.form-row { display: flex; gap: 14px; margin-bottom: 14px; }
.field { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.field.wide { flex: 2; }
.field label { font-size: 12.5px; color: var(--ink-soft); }
.progress-row { display: flex; align-items: center; gap: 12px; margin: 16px 0 6px; }
.bar { flex: 1; height: 8px; background: var(--bg-deep); border-radius: 4px; overflow: hidden; }
.bar-inner { height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand-deep)); transition: width 0.2s; }
.bar-text { font-size: 12.5px; color: var(--ink-soft); min-width: 38px; text-align: right; }
.upload-actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 18px; }
</style>
