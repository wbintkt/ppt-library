import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import FileDetailView from '../views/FileDetailView.vue'
import DuplicateReview from '../components/DuplicateReview.vue'
import { api } from '../api'
vi.mock('../api',async()=>{const real=await vi.importActual<any>('../api');return {...real,api:{...real.api,getFile:vi.fn(),listPages:vi.fn(),management:vi.fn(),deletePages:vi.fn(),duplicates:vi.fn(),resolveDuplicate:vi.fn()}}})
vi.mock('../toast',()=>({toast:vi.fn()}))
const old={id:3,file_id:1,page_no:1,title:'已有页面',file_name:'旧文件.pptx',tags:'无人机'}
const fresh={id:4,file_id:2,page_no:1,title:'新上传页面',file_name:'新文件.pptx',tags:'无人机'}
const dialog={template:'<div><slot/><slot name="footer"/></div>'}
beforeEach(()=>{
 vi.clearAllMocks()
 vi.mocked(api.getFile).mockResolvedValue({id:1,name:'测试文件',page_count:2,status:'ready',category:'素材',tags:'',source:'',file_size:10,error_message:'',progress:100,upload_time:'',update_time:''})
 vi.mocked(api.listPages).mockResolvedValue({total:2,items:[{...old,text:'内容',file_category:'',file_source:'',embedding_status:'done'},{...old,id:5,page_no:2,title:'第二页',text:'内容',file_category:'',file_source:'',embedding_status:'done'}]})
 vi.mocked(api.management).mockResolvedValue({files:{}})
 vi.mocked(api.deletePages).mockResolvedValue({ok:true})
 vi.mocked(api.duplicates).mockResolvedValue({total:1,items:[{id:8,new_page:fresh,old_page:old,similarity:.99,reason:'语义与正文内容均高度相似'}]})
 vi.mocked(api.resolveDuplicate).mockResolvedValue({ok:true})
})
describe('页面管理',()=>{
 it('删除必须确认，提交稳定页面 ID 而不是显示页码',async()=>{
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/file/:id',component:FileDetailView}]})
  await router.push('/file/1');await router.isReady()
  const w=mount(FileDetailView,{global:{plugins:[router],stubs:{AppDialog:dialog,PreviewModal:true}}});await flushPromises()
  expect(w.text()).toContain('无人机')
  await w.get('input[aria-label="选择第 2 页"]').setValue(true)
  await w.findAll('button').find(b=>b.text().includes('删除选中'))!.trigger('click')
  expect(api.deletePages).not.toHaveBeenCalled()
  await w.findAll('button').find(b=>b.text()==='确认删除')!.trigger('click');await flushPromises()
  expect(api.deletePages).toHaveBeenCalledWith(1,[5]);w.unmount()
 })
 it('保留已有页需确认删除新页，两页都保留不删除页面',async()=>{
  const w=mount(DuplicateReview,{global:{stubs:{AppDialog:dialog,PreviewModal:true}}});await flushPromises()
  await w.findAll('button').find(b=>b.text()==='保留已有页，删除新页')!.trigger('click')
  expect(api.resolveDuplicate).not.toHaveBeenCalled()
  await w.findAll('button').find(b=>b.text()==='确认处理')!.trigger('click');await flushPromises()
  expect(api.resolveDuplicate).toHaveBeenCalledWith(8,'keep_old')
  await w.findAll('button').find(b=>b.text()==='两页都保留')!.trigger('click');await flushPromises()
  expect(api.resolveDuplicate).toHaveBeenLastCalledWith(8,'keep_both');w.unmount()
 })
})
