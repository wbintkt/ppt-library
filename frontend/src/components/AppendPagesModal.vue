<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { toast } from '../toast'
import AppDialog from './AppDialog.vue'
const props=defineProps<{fileId:number}>()
const emit=defineEmits<{close:[];uploaded:[]}>()
const file=ref<File|null>(null)
const selection=ref('')
const busy=ref(false)
const error=ref('')
function pick(e:Event){file.value=(e.target as HTMLInputElement).files?.[0]||null;error.value=''}
async function upload(){
  if(!file.value)return
  busy.value=true;error.value=''
  try{
    const r=await api.appendPages(props.fileId,file.value,selection.value)
    toast(`已接收 ${r.pages} 页，正在追加并生成标签`)
    emit('uploaded');emit('close')
  }catch(e:any){error.value=e.message}finally{busy.value=false}
}
</script>
<template>
  <AppDialog title="追加页面" @close="!busy && emit('close')">
    <div class="append-form">
      <p>将新的页面追加到当前文件末尾，原有页面保持原顺序。</p>
      <label class="pick">选择 PPTX 文件<input type="file" accept=".pptx" :disabled="busy" @change="pick"></label>
      <label>导入页码 <span>留空导入全部可见页</span><input v-model="selection" class="text-input" placeholder="例如：1,3-5" :disabled="busy"></label>
      <p class="hint">使用与当前文件相同尺寸的 PPTX。隐藏页不计入页码。上传后自动生成标签，并检查与已有素材的重复页面。</p>
      <p v-if="error" role="alert" class="error">{{error}}</p>
    </div>
    <template #footer><button class="btn" :disabled="busy" @click="emit('close')">取消</button><button class="btn primary" :disabled="busy||!file" @click="upload">{{busy?'正在上传…':'上传并追加'}}</button></template>
  </AppDialog>
</template>
<style scoped>
.append-form{padding:24px;display:grid;gap:24px}.append-form p{line-height:1.8;color:var(--ink-soft)}label{display:grid;gap:10px;font-size:14px}label span,.hint{font-size:12px;color:var(--ink-faint)}.pick{border:1px dashed var(--line);border-radius:8px;padding:20px}.error{color:var(--danger)!important}
</style>
