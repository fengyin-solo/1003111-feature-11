<template>
  <section class="page" data-module="personnel">
    <header class="page-head">
      <div>
        <h2>人员定位管理</h2>
        <p class="page-desc">维护定位终端，支持跨页多选批量处置；提交前给出受影响台数，不满足条件的终端逐台回执原因。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openCarriers">携带人员名单（{{ stats['携带人员名单'] ?? 0 }}）</button>
        <button class="btn" type="button" @click="exportRows">导出人员定位清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>终端编号</span>
        <input v-model="keyword" placeholder="按终端编号检索" />
      </label>
      <label class="filter-item">
        <span>终端状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <span class="batch-count">
        已勾选 <strong>{{ selection.selectedCount }}</strong> 台（跨页累计，刷新不丢失）
      </span>
      <button
        v-for="action in actions"
        :key="action"
        class="btn primary"
        type="button"
        :disabled="!selection.selectedCount || submitting"
        @click="openBatchConfirm(action)"
      >
        批量{{ action }}
      </button>
      <button class="btn ghost" type="button" :disabled="!selection.selectedCount" @click="clearSelection">
        清空勾选
      </button>
      <span class="batch-tip">提示：重复勾选同一台只算一次；同一组终端重复提交只生效一次。</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="pageAllChecked"
              :indeterminate.prop="pageIndeterminate"
              @change="toggleCurrentPage(($event.target as HTMLInputElement).checked)"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-selected': selection.isSelected(Number(row.id)) }">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selection.isSelected(Number(row.id))"
              @change="selection.toggle(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <span v-if="column === '终端状态'" class="status-tag" :class="statusClass(String(row[column]))">{{ row[column] ?? '—' }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无人员定位数据，可先调整筛选条件</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        <span>共 {{ total }} 台</span>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 提交前核对弹窗 -->
    <div v-if="confirmState.open" class="modal-mask" @click.self="closeBatchConfirm">
      <div class="modal-dialog modal-wide">
        <header class="modal-head">
          <h3>批量{{ confirmState.action }} · 提交前核对</h3>
          <button class="link" type="button" @click="closeBatchConfirm">关闭</button>
        </header>
        <div v-if="preview" class="modal-body">
          <div class="confirm-summary">
            <span>勾选去重后 <strong>{{ preview.selected }}</strong> 台</span>
            <span v-if="preview.duplicates" class="warn-text">重复勾选已合并 {{ preview.duplicates }} 台</span>
            <span class="ok-text">预计生效 <strong>{{ preview.affected }}</strong> 台</span>
            <span class="warn-text">将跳过 {{ preview.skipped }} 台</span>
          </div>
          <p v-if="preview.missing_ids.length" class="warn-text">
            以下 id 在最新列表中已不存在，将原样跳过：{{ preview.missing_ids.join('、') }}
          </p>
          <label class="filter-item remark-line">
            <span>处置备注（写入值班台账）</span>
            <input v-model="batchRemark" placeholder="如：白班统一换卡 / 低电集中处置" />
          </label>
          <div class="receipt-table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>终端编号</th>
                  <th>携带人员</th>
                  <th>所在位置</th>
                  <th>当前状态</th>
                  <th>处置后</th>
                  <th>核对结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in preview.receipts" :key="String(item.terminal_id)">
                  <td>{{ item.终端编号 }}</td>
                  <td>{{ item.携带人员 }}</td>
                  <td>{{ terminalLocation(item.terminal_id) }}</td>
                  <td>{{ item.before_status ?? '—' }}</td>
                  <td>{{ item.after_status ?? '—' }}</td>
                  <td :class="item.result === 'succeeded' ? 'ok-text' : 'warn-text'">
                    {{ item.result === 'succeeded' ? '将处置' : `跳过：${item.reason}` }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="modal-body loading-state">正在按最新数据重新核对清单…</div>
        <footer class="modal-foot">
          <button class="btn" type="button" :disabled="loadingPreview" @click="refreshPreview">重新拉取核对</button>
          <button class="btn ghost" type="button" @click="closeBatchConfirm">取消</button>
          <button class="btn primary" type="button" :disabled="!preview || submitting" @click="submitBatch">
            确认提交（{{ preview?.affected ?? 0 }} 台）
          </button>
        </footer>
      </div>
    </div>

    <!-- 处置结果回执弹窗 -->
    <div v-if="resultState.open" class="modal-mask" @click.self="resultState.open = false">
      <div class="modal-dialog modal-wide">
        <header class="modal-head">
          <h3>批量{{ resultState.action }} · 处置回执</h3>
          <button class="link" type="button" @click="resultState.open = false">关闭</button>
        </header>
        <div v-if="batchResult" class="modal-body">
          <p :class="batchResult.skipped ? 'warn-text' : 'ok-text'">
            {{ batchResult.message }}
            <span v-if="batchResult.replayed" class="replay-tag">该组终端已提交过，本次为首次结果回放，未重复生效</span>
          </p>
          <p class="batch-meta">
            批次号 {{ batchResult.batch_no }} · 值班人 {{ batchResult.operator }} · {{ batchResult.finished_at }}
            · 已同步值班台账「{{ resultLedgerName }}」
          </p>
          <div class="receipt-table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>终端编号</th>
                  <th>携带人员</th>
                  <th>处置前</th>
                  <th>处置后</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in batchResult.receipts" :key="String(item.terminal_id)">
                  <td>{{ item.终端编号 }}</td>
                  <td>{{ item.携带人员 }}</td>
                  <td>{{ item.before_status ?? '—' }}</td>
                  <td>{{ item.after_status ?? '—' }}</td>
                  <td :class="item.result === 'succeeded' ? 'ok-text' : 'warn-text'">
                    {{ resultLabel(item.result) }}<template v-if="item.reason">：{{ item.reason }}</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="resultState.open = false">关闭</button>
          <button class="btn primary" type="button" @click="goLedger">前往值班台账</button>
        </footer>
      </div>
    </div>

    <!-- 携带人员名单弹窗 -->
    <div v-if="carrierState.open" class="modal-mask" @click.self="carrierState.open = false">
      <div class="modal-dialog modal-wide">
        <header class="modal-head">
          <h3>携带人员名单（{{ carrierState.items.length }} 人）</h3>
          <button class="link" type="button" @click="carrierState.open = false">关闭</button>
        </header>
        <div class="modal-body">
          <p class="batch-tip">已办理更换（换卡停用）的终端携带人自动移出名单，与入井管理在井人数联动。</p>
          <div class="receipt-table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>终端编号</th>
                  <th>携带人员</th>
                  <th>所属班组</th>
                  <th>所在位置</th>
                  <th>终端状态</th>
                  <th>入井状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in carrierState.items" :key="String(item.终端编号)">
                  <td>{{ item.终端编号 }}</td>
                  <td>{{ item.携带人员 }}</td>
                  <td>{{ item.所属班组 || '—' }}</td>
                  <td>{{ item.所在位置 }}</td>
                  <td>{{ item.终端状态 }}</td>
                  <td>{{ item.入井状态 || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import {
  usePersonnelSelectionStore,
  type BatchPreview,
  type BatchReceipt,
  type BatchResult,
} from '@/stores/personnelSelection'

type Row = Record<string, string | number | null>
interface CarrierItem {
  终端编号: string
  携带人员: string
  所属班组: string
  所在位置: string
  终端状态: string
  入井状态: string
}

const ENDPOINT = '/api/personnel'
const PAGE_SIZE = 20
const columns = ['终端编号', '携带人员', '所在位置', '入井时刻', '区域停留', '定位精度', '信号强度', '终端状态']
const actions = ['记录离线', '低电提醒', '办理更换']
const statuses = ['在线', '离线', '低电量', '已更换']

const router = useRouter()
const session = useSessionStore()
const selection = usePersonnelSelectionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const statusFilter = ref('')
const errorMessage = ref('')
const stats = ref<Record<string, number>>({})
const batchRemark = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const statCards = computed(() => [
  { label: '在册终端', value: stats.value['在册终端'] ?? 0 },
  { label: '在线终端', value: stats.value['在线'] ?? 0 },
  { label: '离线终端', value: stats.value['离线'] ?? 0 },
  { label: '低电终端', value: stats.value['低电量'] ?? 0 },
  { label: '已换卡停用', value: stats.value['已更换'] ?? 0 },
  { label: '携带人员名单', value: stats.value['携带人员名单'] ?? 0 },
])

const pageAllChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => selection.isSelected(Number(row.id))))
const pageIndeterminate = computed(() => {
  const checkedInPage = rows.value.filter((row) => selection.isSelected(Number(row.id))).length
  return checkedInPage > 0 && checkedInPage < rows.value.length
})

const confirmState = reactive({ open: false, action: '' })
const resultState = reactive({ open: false, action: '' })
const carrierState = reactive<{ open: boolean; items: CarrierItem[] }>({ open: false, items: [] })
const preview = ref<BatchPreview | null>(null)
const batchResult = ref<BatchResult | null>(null)
const loadingPreview = ref(false)
const submitting = ref(false)

const resultLedgerName = computed(() => batchResult.value?.ledger?.['台账编号'] ?? '—')

function statusClass(status: string) {
  return {
    'status-online': status === '在线',
    'status-offline': status === '离线',
    'status-low': status === '低电量',
    'status-done': status === '已更换',
  }
}

function resultLabel(result: BatchReceipt['result']) {
  if (result === 'succeeded') return '已处置'
  if (result === 'skipped') return '跳过'
  return '未找到'
}

function terminalLocation(terminalId: number) {
  const terminal = preview.value?.terminals.find((item) => item.id === terminalId)
  return terminal?.所在位置 ?? '—'
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleCurrentPage(checked: boolean) {
  selection.togglePage(rows.value.map((row) => ({ id: Number(row.id) })), checked)
}

function clearSelection() {
  selection.clear()
}

function goPage(target: number) {
  page.value = target
  void reload()
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, operator: session.operator } }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '人员定位动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '人员定位操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  query.set('page', String(page.value))
  query.set('size', String(PAGE_SIZE))
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('定位终端列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '人员定位列表读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats/overview`)
    if (response.ok) {
      stats.value = await response.json()
    }
  } catch {
    // 统计卡片不阻塞主列表
  }
}

async function openBatchConfirm(action: string) {
  confirmState.action = action
  confirmState.open = true
  preview.value = null
  batchRemark.value = ''
  await refreshPreview()
}

async function refreshPreview() {
  loadingPreview.value = true
  errorMessage.value = ''
  try {
    preview.value = await selection.previewBatch(confirmState.action)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量核对失败'
    confirmState.open = false
  } finally {
    loadingPreview.value = false
  }
}

function closeBatchConfirm() {
  confirmState.open = false
  preview.value = null
}

async function submitBatch() {
  if (!preview.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    batchResult.value = await selection.submitBatch(confirmState.action, batchRemark.value)
    resultState.action = confirmState.action
    resultState.open = true
    confirmState.open = false
    preview.value = null
    selection.clear()
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量处置失败'
  } finally {
    submitting.value = false
  }
}

async function openCarriers() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/carriers`)
    if (!response.ok) {
      throw new Error('携带人员名单读取失败')
    }
    const payload = await response.json()
    carrierState.items = payload.items ?? []
    carrierState.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '携带人员名单读取失败'
  }
}

function goLedger() {
  resultState.open = false
  void router.push('/dutylog')
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
