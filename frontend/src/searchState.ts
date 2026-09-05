import { reactive, watch } from 'vue'
import type { SearchItem } from './api'

export type SelectedPage = Pick<SearchItem, 'page_id' | 'page_no' | 'title'>
const SELECTION_KEY = 'ppt_selected_pages_v2'

function restoreSelection(): SelectedPage[] {
  try {
    const data: unknown = JSON.parse(sessionStorage.getItem(SELECTION_KEY) || '[]')
    if (!Array.isArray(data)) return []
    const seen = new Set<number>()
    return data.filter((p): p is SelectedPage => {
      if (!p || !Number.isInteger(p.page_id) || p.page_id <= 0 || !Number.isInteger(p.page_no) || typeof p.title !== 'string' || seen.has(p.page_id)) return false
      seen.add(p.page_id)
      return true
    }).slice(0, 200).map(({ page_id, page_no, title }) => ({ page_id, page_no, title }))
  } catch { return [] }
}

export const searchState = reactive({
  query: '',
  results: [] as SearchItem[],
  selected: restoreSelection(),
  limit: 20,
  hasResults: false,
  compact: false,
})

watch(() => searchState.selected, (pages) => {
  try { sessionStorage.setItem(SELECTION_KEY, JSON.stringify(pages)) } catch { /* Memory state still works. */ }
}, { deep: true, flush: 'sync' })

export function togglePage(page: SelectedPage): boolean {
  const index = searchState.selected.findIndex(p => p.page_id === page.page_id)
  if (index >= 0) searchState.selected.splice(index, 1)
  else {
    if (searchState.selected.length >= 200) return false
    searchState.selected.push({ page_id: page.page_id, page_no: page.page_no, title: page.title })
  }
  return true
}

export function movePage(index: number, direction: -1 | 1) {
  const target = index + direction
  if (index < 0 || index >= searchState.selected.length || target < 0 || target >= searchState.selected.length) return
  const [page] = searchState.selected.splice(index, 1)
  searchState.selected.splice(target, 0, page)
}

export function resetSearchState() {
  searchState.query = ''
  searchState.results = []
  searchState.selected = []
  searchState.hasResults = false
  searchState.limit = 20
}
