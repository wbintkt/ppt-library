<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, imageUrl, type DuplicatePair } from '../api'
import { toast } from '../toast'
import AppDialog from './AppDialog.vue'
import PreviewModal from './PreviewModal.vue'
const props=defineProps<{fileId?:number;revision?:number}>()
const emit=defineEmits<{changed:[]}>()
const pairs=ref<DuplicatePair[]>([]),total=ref(0),loading=ref(false),error=ref(''),busy=ref(false)
const decision=ref<{pair:DuplicatePair;action:string}|null>(null)
const preview=ref<{id:number;title:string}|null>(null)
async function load(){
  loading.value=true
  try{const r=await api.duplicates(props.fileId);pairs.value=r.items;total.value=r.total;error.value=''}
  catch(e:any){error.value=e.message}finally{loading.value=false}
}
async function resolve(pair:DuplicatePair,action:string){
  busy.value=true
  try{await api.resolveDuplicate(pair.id,action);decision.value=null;toast(action==='keep_both'?'已保留两页，不再提醒此组合':'已保留所选页面');await load();emit('changed')}
  catch(e:any){toast(e.message,'error');await load()}finally{busy.value=false}
}
onMounted(load)
watch(()=>[props.fileId,props.revision],load)
</script>
<template>
  <section class="duplicate-review">
    <div class="review-heading"><div><h3>相似页面 <span>{{total}} 组待确认</span></h3><p>仅检查新上传或追加的页面。相似度不代表完全重复，请核对内容后选择保留。</p></div><button class="btn btn-sm" :disabled="loading||busy" @click="load">刷新</button></div>
    <p v-if="error" role="alert">{{error}}</p>
    <p v-else-if="loading&&!pairs.length" class="quiet">正在读取检测结果…</p>
    <p v-else-if="!pairs.length" class="quiet">暂无待处理的相似页面。新素材向量化完成后，检测结果会出现在这里。</p>
    <article v-for="pair in pairs" :key="pair.id" class="pair">
      <div class="pair-meta"><span>{{pair.reason}}</span><span>相似度 {{(pair.similarity*100).toFixed(1)}}%</span></div>
      <div class="compare">
        <button v-for="(p,i) in [pair.new_page,pair.old_page]" :key="p.id" class="compare-page" @click="preview={id:p.id,title:p.title}">
          <span class="side-label">{{i===0?'新上传页面':'已有页面'}}</span>
          <img :src="imageUrl(p.id)" :alt="p.title" loading="lazy">
          <strong>{{p.title||`第 ${p.page_no} 页`}}</strong><span>{{p.file_name}} · 第 {{p.page_no}} 页</span>
        </button>
      </div>
      <div class="pair-actions">
        <button class="btn btn-sm" :disabled="busy" @click="decision={pair,action:'keep_new'}">保留新页，删除已有页</button>
        <button class="btn btn-sm" :disabled="busy" @click="decision={pair,action:'keep_old'}">保留已有页，删除新页</button>
        <button class="btn btn-sm" :disabled="busy" @click="resolve(pair,'keep_both')">两页都保留</button>
      </div>
    </article>
    <p v-if="total>pairs.length" class="quiet">先显示 {{pairs.length}} 组，处理后会继续显示余下结果。</p>
    <AppDialog v-if="decision" title="确认保留页面" @close="!busy&&(decision=null)">
      <div class="confirm-copy"><p>将从素材库中删除{{decision.action==='keep_new'?'已有页':'新上传页'}}：</p><strong>{{decision.action==='keep_new'?decision.pair.old_page.title:decision.pair.new_page.title}}</strong><p>另一页会保留。文件中的页码与下载内容将同步更新。</p></div>
      <template #footer><button class="btn" :disabled="busy" @click="decision=null">取消</button><button class="btn primary" :disabled="busy" @click="resolve(decision.pair,decision.action)">{{busy?'处理中…':'确认处理'}}</button></template>
    </AppDialog>
    <PreviewModal v-if="preview" :page-id="preview.id" :title="preview.title" @close="preview=null"/>
  </section>
</template>
<style scoped>
.duplicate-review{margin:28px 0}.review-heading{display:flex;justify-content:space-between;gap:20px;align-items:start}.review-heading h3{font-size:20px}.review-heading h3 span{font:12px var(--sans);color:var(--brand);margin-left:12px}.review-heading p,.quiet{font-size:13px;color:var(--ink-faint);line-height:1.8;margin:10px 0 20px}.pair{border:1px solid var(--line);border-radius:8px;padding:20px;margin-top:20px;background:var(--white)}.pair-meta{display:flex;justify-content:space-between;gap:12px;color:var(--ink-soft);font-size:12px;margin-bottom:16px}.pair-meta span:last-child{color:var(--brand)}.compare{display:grid;grid-template-columns:1fr 1fr;gap:24px}.compare-page{min-width:0;border:0;background:none;text-align:left;display:grid;gap:9px;color:var(--ink);cursor:pointer}.compare-page img{width:100%;aspect-ratio:16/9;object-fit:contain;background:var(--bg)}.compare-page strong{font-size:14px;font-weight:500}.compare-page>span{font-size:12px;color:var(--ink-faint);word-break:break-all}.compare-page .side-label{color:var(--brand)}.pair-actions{display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end;border-top:1px solid var(--line);padding-top:16px;margin-top:18px}.confirm-copy{padding:24px;line-height:1.9}.confirm-copy p{color:var(--ink-soft)}@media(max-width:650px){.compare{grid-template-columns:1fr}.pair{padding:14px}.review-heading{flex-wrap:wrap}}
</style>
