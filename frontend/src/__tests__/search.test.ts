import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import SearchView from '../views/SearchView.vue'
import PreviewModal from '../components/PreviewModal.vue'
import { api, clearToken, type SearchItem } from '../api'
import { resetSearchState, searchState, togglePage, movePage } from '../searchState'
import { saveBlob } from '../download'

vi.mock('../api', async (original) => {
  const real = await original<typeof import('../api')>()
  return { ...real, api: { ...real.api, search: vi.fn(), getPage: vi.fn(), similarPages: vi.fn(), exportPages: vi.fn() } }
})
vi.mock('../download', () => ({ saveBlob: vi.fn() }))

const item = (id: number, title = `内容 ${id}`, score: number | null = .986): SearchItem => ({ page_id: id, file_id: 1, page_no: id, title, text: '', tags: '', file_name: '来源不应显示.pptx', category: '分类不应显示', score: 1, display_score: score, embedding_status: 'done' })
let wrapper: VueWrapper | undefined
let router: Router
async function open(url = '/') {
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', name: 'search', component: SearchView }, { path: '/file/:id', name: 'file', component: { template: '<div />' } }] })
  await router.push(url)
  await router.isReady()
  wrapper = mount(SearchView, { attachTo: document.body, global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}
function button(text: string) { return wrapper!.findAll('button').find(b => b.text() === text)! }
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }

beforeEach(() => {
  resetSearchState()
  document.body.innerHTML = '<div id="header-search"></div>'
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open') } })
  vi.mocked(api.search).mockResolvedValue({ query: '低空', total: 2, items: [item(1), item(2)] })
  vi.mocked(api.similarPages).mockResolvedValue([])
  vi.mocked(api.getPage).mockImplementation(async id => ({ id, file_id: 1, page_no: id, title: `页面 ${id}`, text: `正文 ${id}`, tags: '', embedding_status: 'done', file_name: '文件', file_category: '', file_source: '' }))
  vi.mocked(api.exportPages).mockResolvedValue(new Blob(['pptx']))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('content search workflow', () => {
  it('keeps the home minimal and submits exactly once with no category', async () => {
    const view = await open()
    expect(view.text()).toContain('找到，恰好那一页')
    expect(view.text()).not.toContain('最近浏览')
    expect(api.search).not.toHaveBeenCalled()
    await view.get('input[type=search]').setValue('低空通信覆盖')
    await view.get('form').trigger('submit')
    await flushPromises()
    expect(api.search).toHaveBeenCalledTimes(1)
    expect(api.search).toHaveBeenCalledWith('低空通信覆盖', '', 20, expect.any(AbortSignal))
    expect(document.querySelector('#header-search form')).not.toBeNull()
    expect(view.text()).toContain('98.6')
    expect(view.text()).not.toContain('来源不应显示')
    expect(view.text()).not.toContain('分类不应显示')
  })

  it('does not submit while confirming a Chinese input-method candidate', async () => {
    const view = await open()
    const event = new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })
    view.get('input[type=search]').element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(api.search).not.toHaveBeenCalled()
  })

  it('selects without opening preview and exports in the chosen order', async () => {
    const view = await open('/?q=低空')
    const checks = view.findAll('input[type=checkbox]')
    await checks[0].setValue(true)
    await checks[1].setValue(true)
    expect(document.querySelector('dialog')).toBeNull()
    expect(searchState.selected.map(p => p.page_id)).toEqual([1, 2])
    await button('查看已选').trigger('click')
    expect(document.querySelector('dialog[open]')).not.toBeNull()
    ;(document.querySelector('[aria-label="上移：内容 2"]') as HTMLButtonElement).click()
    await flushPromises()
    ;([...document.querySelectorAll('dialog button')].find(b => b.textContent === '导出 2 页') as HTMLButtonElement).click()
    await flushPromises()
    expect(api.exportPages).toHaveBeenCalledWith([2, 1])
    expect(saveBlob).toHaveBeenCalledOnce()
    expect(searchState.selected).toHaveLength(2)
  })

  it('ignores an older response even when a cancelled backend completes late', async () => {
    const old = deferred<any>()
    vi.mocked(api.search).mockImplementation(q => q === '旧查询' ? old.promise : Promise.resolve({ query: q, total: 1, items: [item(3, '新结果')] }))
    const view = await open('/?q=旧查询')
    const firstSignal = vi.mocked(api.search).mock.calls[0][3]!
    await router.push('/?q=新查询')
    await flushPromises()
    expect(firstSignal.aborted).toBe(true)
    old.resolve({ query: '旧查询', total: 1, items: [item(4, '旧结果')] })
    await flushPromises()
    expect(view.text()).toContain('新结果')
    expect(view.text()).not.toContain('旧结果')
  })

  it('restores the last completed search after cancel and does not refetch it', async () => {
    const view = await open('/?q=低空')
    vi.mocked(api.search).mockReturnValueOnce(new Promise(() => {}))
    await router.push('/?q=应急')
    await flushPromises()
    await button('取消搜索').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.q).toBe('低空')
    expect(view.text()).toContain('内容 1')
    expect(api.search).toHaveBeenCalledTimes(2)
  })

  it('preserves selection and cached results when revisiting the search', async () => {
    const view = await open('/?q=低空')
    await view.findAll('input[type=checkbox]')[0].setValue(true)
    view.unmount(); wrapper = undefined
    await open('/?q=低空')
    expect(api.search).toHaveBeenCalledTimes(1)
    expect(wrapper!.get('input[type=checkbox]').element).toHaveProperty('checked', true)
    expect(JSON.parse(sessionStorage.getItem('ppt_selected_pages_v2')!)).toEqual([{ page_id: 1, page_no: 1, title: '内容 1' }])
  })

  it('shows missing and zero scores honestly and offers recovery for errors', async () => {
    vi.mocked(api.search).mockResolvedValueOnce({ query: '低空', total: 2, items: [item(1, '零匹配', 0), item(2, '缺失分数', null)] })
    const view = await open('/?q=低空')
    expect(view.text()).toContain('0.0%')
    expect(view.get('.score-unavailable').text()).toBe('—')
    vi.mocked(api.search).mockRejectedValueOnce(new Error('服务繁忙'))
    await router.push('/?q=应急'); await flushPromises()
    expect(view.get('[role=alert]').text()).toContain('服务繁忙')
    await button('重新搜索').trigger('click'); await flushPromises()
    expect(view.find('[role=alert]').exists()).toBe(false)
  })

  it('offers a useful empty state and can increase the result limit', async () => {
    vi.mocked(api.search).mockResolvedValueOnce({ query: '空', total: 0, items: [] })
    const view = await open('/?q=空')
    expect(view.text()).toContain('还没有找到合适的内容')
    vi.mocked(api.search).mockResolvedValueOnce({ query: '低空', total: 20, items: Array.from({ length: 20 }, (_, n) => item(n + 1)) })
    await router.push('/?q=低空'); await flushPromises()
    await button('查看更多相关页面').trigger('click'); await flushPromises()
    expect(api.search).toHaveBeenLastCalledWith('低空', '', 50, expect.any(AbortSignal))
  })
})

describe('preview and selection safety', () => {
  it('loads the main page without waiting for recommendations, keeps title current', async () => {
    vi.mocked(api.similarPages).mockReturnValue(new Promise(() => {}))
    wrapper = mount(PreviewModal, { attachTo: document.body, props: { pageId: 1, title: '旧标题', pageIds: [1, 2], selectedIds: [] }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(document.body.textContent).toContain('正文 1')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('dialog')?.getAttribute('aria-label')).toBe('页面 2 · 第 2 页')
    expect(document.body.textContent).toContain('正文 2')
    expect(document.body.textContent).not.toContain('旧标题')
    document.querySelector('dialog')?.dispatchEvent(new Event('cancel'))
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('guards selection limits, reorder boundaries, and clears state on logout', () => {
    for (let n = 1; n <= 200; n++) expect(togglePage(item(n))).toBe(true)
    expect(togglePage(item(201))).toBe(false)
    movePage(0, -1)
    movePage(199, 1)
    expect(searchState.selected[0].page_id).toBe(1)
    localStorage.setItem('ppt_token', 'test-session')
    clearToken()
    expect(localStorage.getItem('ppt_token')).toBeNull()
    expect(searchState.selected).toHaveLength(0)
    expect(JSON.parse(sessionStorage.getItem('ppt_selected_pages_v2')!)).toEqual([])
  })
})
