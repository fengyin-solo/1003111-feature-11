<template>
  <section class="page" data-module="personnel">
    <header class="page-head">
      <div>
        <h2>人员定位管理</h2>
        <p class="page-desc">维护定位终端，支持跨页多选后整组批量处置，处理结果同步值班台账、携带人员名单与在井人数。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记定位终端</button>
        <button class="btn" type="button" @click="exportRows">导出人员定位清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selected.size" class="batch-bar">
      <span class="count">已选 {{ selected.size }} 台（跨页勾选保留）</span>
      <select v-model="batchAction" class="input">
        <option v-for="action in actions" :key="action" :value="action">{{ action }}</option>
      </select>
      <button class="btn primary" type="button" @click="openPreview">核对清单</button>
      <button class="btn ghost" type="button" @click="clearSelection">清空选择</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              :checked="pageAllSelected"
              title="勾选本页"
              @change="togglePage"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              type="checkbox"
              :checked="selected.has(Number(row.id))"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无人员定位数据，可先登记定位终端</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条人员定位记录</span>
      <span class="pager">
        <button class="btn ghost" type="button" :disabled="page <= 1" @click="turnPage(-1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn ghost" type="button" :disabled="page >= pageCount" @click="turnPage(1)">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section v-if="preview" class="panel" data-panel="preview">
      <h3>提交前核对 · {{ preview.动作 }}</h3>
      <p class="summary">
        <span>勾选 {{ preview.提交台数 }} 台</span>
        <span>将处理 <strong>{{ preview.可处理台数 }}</strong> 台</span>
        <span>跳过 <strong>{{ preview.跳过台数 }}</strong> 台</span>
      </p>
      <table class="data-table">
        <thead>
          <tr><th>终端编号</th><th>携带人员</th><th>当前状态</th><th>结论</th><th>原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in preview.明细" :key="item.id">
            <td>{{ item.终端编号 || `#${item.id}` }}</td>
            <td>{{ item.携带人员 || '—' }}</td>
            <td>{{ item.当前状态 || '—' }}</td>
            <td><span class="tag" :class="item.可处理 ? 'ok' : 'skip'">{{ item.可处理 ? '将处理' : '将跳过' }}</span></td>
            <td>{{ item.原因 || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="panel-actions">
        <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
          {{ submitting ? '提交中…' : `确认提交（影响 ${preview.可处理台数} 台）` }}
        </button>
        <button class="btn ghost" type="button" @click="preview = null">返回修改</button>
      </p>
    </section>

    <section v-if="result" class="panel" data-panel="result">
      <h3>处置回执 · {{ result.动作 }} <span v-if="result.重复提交" class="tag skip">重复提交，未重复生效</span></h3>
      <p class="summary">
        <span>成功 <strong>{{ result.成功台数 }}</strong> 台</span>
        <span>跳过 <strong>{{ result.跳过台数 }}</strong> 台</span>
        <span>在井人数变动 <strong>{{ result.在井人数变动 }}</strong></span>
        <span>台账编号 <strong>{{ result.台账编号 }}</strong></span>
      </p>
      <table class="data-table">
        <thead>
          <tr><th>终端编号</th><th>携带人员</th><th>结果</th><th>原因 / 说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in result.回执" :key="item.id">
            <td>{{ item.终端编号 || `#${item.id}` }}</td>
            <td>{{ item.携带人员 || '—' }}</td>
            <td><span class="tag" :class="item.结果 === '成功' ? 'ok' : 'skip'">{{ item.结果 }}</span></td>
            <td>{{ item.结果 === '成功' ? `已处理${item.同步销记在井记录 ? `，同步销记在井记录 ${item.同步销记在井记录} 条` : ''}` : item.原因 }}</td>
          </tr>
        </tbody>
      </table>
      <p class="panel-actions">
        <button class="btn ghost" type="button" @click="result = null">收起回执</button>
      </p>
    </section>

    <div class="panel-grid">
      <section class="panel" data-panel="carriers">
        <h3>携带人员名单</h3>
        <table class="data-table">
          <thead>
            <tr><th>携带人员</th><th>终端编号</th><th>终端状态</th><th>是否在井</th><th>最近处置</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in carriers" :key="item.终端编号">
              <td>{{ item.携带人员 }}</td>
              <td>{{ item.终端编号 }}</td>
              <td>{{ item.终端状态 }}</td>
              <td>{{ item.是否在井 }}</td>
              <td>{{ item.最近处置 }}</td>
            </tr>
            <tr v-if="!carriers.length"><td colspan="5" class="empty-state">暂无携带人员</td></tr>
          </tbody>
        </table>
      </section>

      <section class="panel" data-panel="ledger">
        <h3>值班台账</h3>
        <table class="data-table">
          <thead>
            <tr><th>台账编号</th><th>处置动作</th><th>提交</th><th>成功</th><th>跳过</th><th>在井变动</th><th>办理时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in ledger" :key="item.台账编号">
              <td>{{ item.台账编号 }}</td>
              <td>{{ item.处置动作 }}</td>
              <td>{{ item.提交台数 }}</td>
              <td>{{ item.成功台数 }}</td>
              <td>{{ item.跳过台数 }}</td>
              <td>{{ item.在井人数变动 }}</td>
              <td>{{ item.办理时间 }}</td>
            </tr>
            <tr v-if="!ledger.length"><td colspan="7" class="empty-state">暂无批量处置记录</td></tr>
          </tbody>
        </table>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type PreviewItem = { id: number; 终端编号: string; 携带人员: string; 当前状态: string; 可处理: boolean; 原因: string }
type Preview = { 动作: string; 提交台数: number; 可处理台数: number; 跳过台数: number; 明细: PreviewItem[] }
type Receipt = PreviewItem & { 结果: string; 同步销记在井记录?: number }
type BatchResult = {
  动作: string
  成功台数: number
  跳过台数: number
  在井人数变动: number
  台账编号: string
  回执: Receipt[]
  重复提交: boolean
}
type Carrier = { 携带人员: string; 终端编号: string; 终端状态: string; 是否在井: string; 最近处置: string }
type LedgerRow = { 台账编号: string; 处置动作: string; 提交台数: number; 成功台数: number; 跳过台数: number; 在井人数变动: number; 办理时间: string }

const ENDPOINT = '/api/personnel'
const PAGE_SIZE = 10
const columns = ["终端编号", "携带人员", "所在位置", "入井时刻", "区域停留", "定位精度", "信号强度", "终端状态"]
const actions = ["记录离线", "低电提醒", "办理更换"]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([{ label: '在线终端', value: 0 }, { label: '离线终端', value: 0 }, { label: '低电终端', value: 0 }, { label: '已更换', value: 0 }])

// 跨页勾选：id -> 行快照，翻页、改筛选都不丢。
const selected = reactive(new Map<number, Row>())
const batchAction = ref(actions[1])
const preview = ref<Preview | null>(null)
const result = ref<BatchResult | null>(null)
const submitting = ref(false)
const carriers = ref<Carrier[]>([])
const ledger = ref<LedgerRow[]>([])
let requestId = ''

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const pageAllSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selected.has(Number(row.id))))

function newRequestId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function toggleRow(row: Row) {
  const id = Number(row.id)
  if (selected.has(id)) {
    selected.delete(id)
  } else {
    selected.set(id, row)
  }
  preview.value = null
}

function togglePage() {
  if (pageAllSelected.value) {
    rows.value.forEach((row) => selected.delete(Number(row.id)))
  } else {
    rows.value.forEach((row) => selected.set(Number(row.id), row))
  }
  preview.value = null
}

function clearSelection() {
  selected.clear()
  preview.value = null
  result.value = null
}

function resetFilters() {
  filters.value = {}
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '定位终端登记入口尚未接入审批流'
}

function turnPage(step: number) {
  const next = page.value + step
  if (next < 1 || next > pageCount.value) return
  page.value = next
  void reload()
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('人员定位动作未生效，请稍后重试')
    }
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '人员定位操作失败'
  }
}

async function openPreview() {
  // 提交前按最新状态重新拉取勾选清单核对，并给出会受影响的台数。
  errorMessage.value = ''
  result.value = null
  requestId = newRequestId()
  try {
    const response = await request(`${ENDPOINT}/batch/preview`, {
      method: 'POST',
      body: JSON.stringify({ action: batchAction.value, entry_ids: [...selected.keys()] }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '清单核对失败')
    }
    preview.value = payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清单核对失败'
  }
}

async function submitBatch() {
  if (submitting.value || !preview.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ action: batchAction.value, entry_ids: [...selected.keys()], request_id: requestId }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '批量处置未生效，请稍后重试')
    }
    result.value = payload
    preview.value = null
    selected.clear()
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量处置失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({ ...filters.value, page: String(page.value), size: String(PAGE_SIZE) }).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
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

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    const payload = await response.json()
    stats.value = [
      { label: '在线终端', value: payload['在线'] ?? 0 },
      { label: '离线终端', value: payload['离线'] ?? 0 },
      { label: '低电终端', value: payload['低电量'] ?? 0 },
      { label: '已更换', value: payload['已更换'] ?? 0 },
    ]
  } catch {
    // 统计卡片失败不阻塞列表
  }
}

async function loadCarriers() {
  try {
    const response = await request(`${ENDPOINT}/carriers`)
    carriers.value = (await response.json()).items ?? []
  } catch {
    carriers.value = []
  }
}

async function loadLedger() {
  try {
    const response = await request(`${ENDPOINT}/ledger`)
    ledger.value = (await response.json()).items ?? []
  } catch {
    ledger.value = []
  }
}

async function refreshAll() {
  await Promise.all([reload(), loadStats(), loadCarriers(), loadLedger()])
}

onMounted(refreshAll)
</script>
