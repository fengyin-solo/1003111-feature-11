<template>
  <section class="page" data-module="dutylog">
    <header class="page-head">
      <div>
        <h2>人员定位值班台账</h2>
        <p class="page-desc">人员定位单台/批量处置结果自动登记到这里，逐台跳过原因留痕，值班长核对后销项。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出台账</button>
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
        <span>关键字</span>
        <input v-model="keyword" placeholder="按台账编号/处置事项/值班人员检索" />
      </label>
      <label class="filter-item">
        <span>台账状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>跳过明细</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <button v-if="Number(row.跳过台数) > 0" class="link" type="button" @click="openDetail(row)">
              查看 {{ row.跳过台数 }} 台原因
            </button>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-if="row.status === '已登记'"
              class="link"
              type="button"
              @click="review(row)"
            >
              核对销项
            </button>
            <span v-else class="batch-tip">已核对</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无值班台账记录，去人员定位执行处置后会自动登记</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        <span>共 {{ total }} 条</span>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detailState.open" class="modal-mask" @click.self="detailState.open = false">
      <div class="modal-dialog modal-wide">
        <header class="modal-head">
          <h3>{{ detailState.row?.['台账编号'] }} · 跳过终端与原因</h3>
          <button class="link" type="button" @click="detailState.open = false">关闭</button>
        </header>
        <div class="modal-body">
          <p class="batch-tip">{{ detailState.row?.['处置事项'] }} · {{ detailState.row?.['处置时间'] }}</p>
          <table class="data-table">
            <thead>
              <tr>
                <th>终端编号</th>
                <th>携带人员</th>
                <th>跳过原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in skipDetails" :key="index">
                <td>{{ item.终端编号 }}</td>
                <td>{{ item.携带人员 }}</td>
                <td class="warn-text">{{ item.原因 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type SkipDetail = { 终端编号: string; 携带人员: string; 原因: string }
type Row = Record<string, string | number | null | SkipDetail[]>

const ENDPOINT = '/api/dutylog'
const PAGE_SIZE = 20
const columns = ['台账编号', '处置事项', '批次号', '涉及终端数', '成功台数', '跳过台数', '值班人员', '处置时间', '备注', 'status']
const statuses = ['已登记', '已核对', '已归档']

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const statusFilter = ref('')
const errorMessage = ref('')
const detailState = reactive<{ open: boolean; row: Row | null }>({ open: false, row: null })
const skipDetails = computed<SkipDetail[]>(() => {
  const value = detailState.row?.['跳过明细']
  return Array.isArray(value) ? (value as SkipDetail[]) : []
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const statCards = computed(() => {
  const pending = rows.value.filter((row) => row.status === '已登记').length
  const skipped = rows.value.reduce((sum, row) => sum + Number(row.跳过台数 ?? 0), 0)
  return [
    { label: '本页待核对', value: pending },
    { label: '本页跳过台次', value: skipped },
    { label: '台账总数', value: total.value },
  ]
})

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function goPage(target: number) {
  page.value = target
  void reload()
}

function openDetail(row: Row) {
  detailState.row = row
  detailState.open = true
}

async function review(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, { method: 'POST' })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '台账核对失败')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '台账核对失败'
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
      throw new Error('值班台账读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '值班台账读取失败'
  }
}

onMounted(reload)
</script>
