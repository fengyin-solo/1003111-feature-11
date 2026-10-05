import { defineStore } from 'pinia'

import { request } from '@/api/client'

/** 跨页勾选的定位终端：勾完翻页、刷新页面都保留，提交前再按 id 重新回捞核对。 */
export interface SelectedTerminal {
  id: number
  终端编号: string
  携带人员: string
  所在位置: string
  status: string
}

interface SelectionResponse {
  selected: number
  duplicates: number
  terminals: SelectedTerminal[]
  missing_ids: number[]
}

export interface BatchReceipt {
  terminal_id: number
  终端编号: string
  携带人员: string
  result: 'succeeded' | 'skipped' | 'not_found'
  reason: string | null
  before_status: string | null
  after_status: string | null
}

export interface BatchPreview {
  action: string
  selected: number
  duplicates: number
  affected: number
  skipped: number
  terminals: SelectedTerminal[]
  missing_ids: number[]
  receipts: BatchReceipt[]
}

export interface BatchLedger {
  台账编号: string
  [key: string]: unknown
}

export interface BatchResult extends BatchPreview {
  ok: boolean
  replayed: boolean
  batch_no: string
  message: string
  succeeded: number
  operator: string
  finished_at: string
  ledger?: BatchLedger
}

const STORAGE_KEY = 'personnel-selected-terminal-ids'

function loadIds(): number[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'number') : []
  } catch {
    return []
  }
}

export const usePersonnelSelectionStore = defineStore('personnel-selection', {
  state: () => ({
    selectedIds: loadIds() as number[],
  }),
  getters: {
    selectedCount: (state) => state.selectedIds.length,
  },
  actions: {
    persist() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.selectedIds))
    },
    isSelected(id: number) {
      return this.selectedIds.includes(id)
    },
    toggle(id: number) {
      if (this.isSelected(id)) {
        this.selectedIds = this.selectedIds.filter((item) => item !== id)
      } else {
        this.selectedIds = [...this.selectedIds, id]
      }
      this.persist()
    },
    /** 当前页全选/取消；其他页已勾的不清空。 */
    togglePage(rows: { id: number }[], checked: boolean) {
      const pageIds = new Set(rows.map((row) => row.id))
      if (checked) {
        const merged = new Set([...this.selectedIds, ...pageIds])
        this.selectedIds = [...merged]
      } else {
        this.selectedIds = this.selectedIds.filter((id) => !pageIds.has(id))
      }
      this.persist()
    },
    clear() {
      this.selectedIds = []
      this.persist()
    },
    /** 提交前按 id 清单重新回捞终端最新数据，跨页勾选在此统一核对。 */
    async fetchSelection(): Promise<SelectionResponse> {
      const response = await request('/api/personnel/batch/selection', {
        method: 'POST',
        body: JSON.stringify({ terminal_ids: this.selectedIds }),
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}))
        throw new Error(detail.detail ?? '勾选清单核对失败，请稍后重试')
      }
      return (await response.json()) as SelectionResponse
    },
    /** 提交前试算：只回预计生效台数与逐台跳过原因，不改任何数据。 */
    async previewBatch(action: string): Promise<BatchPreview> {
      const response = await request('/api/personnel/batch/preview', {
        method: 'POST',
        body: JSON.stringify({ action, terminal_ids: this.selectedIds }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail ?? '批量试算失败，请稍后重试')
      }
      return payload as BatchPreview
    },
    /** 整组提交：跳过的终端原样返回原因，成功的照常处理；重复提交只回放首次结果。 */
    async submitBatch(action: string, remark?: string): Promise<BatchResult> {
      const response = await request('/api/personnel/batch/actions', {
        method: 'POST',
        body: JSON.stringify({
          action,
          terminal_ids: this.selectedIds,
          remark: remark ?? undefined,
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail ?? '批量处置未生效，请稍后重试')
      }
      return payload as BatchResult
    },
  },
})
