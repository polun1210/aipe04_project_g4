<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getReports, taipeiDateTime, type ReportSummary } from '../api/reports'
import { errorMessage } from '../api/client'
const from = ref('')
const to = ref('')
const reports = ref<ReportSummary[]>([])
const busy = ref(false)
const error = ref('')
async function search() {
  if (busy.value) return
  error.value = ''
  if (from.value && to.value && from.value > to.value) {
    error.value = '開始日期不可晚於結束日期。'
    return
  }
  busy.value = true
  reports.value = []
  try {
    reports.value = await getReports(from.value, to.value)
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    busy.value = false
  }
}
function quick(range: 'today' | 'week' | 'month' | 'this-month' | 'all') {
  if (busy.value) return
  // 固定以台灣日曆日期計算，避免使用者裝置時區造成前後一天的差異。
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const part = (type: string) => parts.find((item) => item.type === type)!.value
  const today = `${part('year')}-${part('month')}-${part('day')}`
  const start = new Date(`${today}T00:00:00Z`)
  if (range === 'week') start.setUTCDate(start.getUTCDate() - 6)
  if (range === 'month') start.setUTCDate(start.getUTCDate() - 29)
  if (range === 'this-month') start.setUTCDate(1)
  from.value = range === 'all' ? '' : start.toISOString().slice(0, 10)
  to.value = range === 'all' ? '' : today
  void search()
}
onMounted(search)
</script>
<template>
  <main>
    <p><RouterLink to="/member-center">← 返回會員中心</RouterLink></p>
    <h1>報告記錄</h1>
    <p>查看過去的營養補充評估報告。目前顯示測試帳號資料，後端重啟後記錄可能消失。</p>
    <form @submit.prevent="search">
      <fieldset :disabled="busy">
        <legend>搜尋報告（台灣時間，含開始與結束當天）</legend>
        <p>
          <label for="date-from">開始日期</label><input id="date-from" v-model="from" type="date" />
        </p>
        <p><label for="date-to">結束日期</label><input id="date-to" v-model="to" type="date" /></p>
        <button type="submit">搜尋</button>
        <button type="button" @click="quick('today')">今天</button>
        <button type="button" @click="quick('week')">最近 7 天</button>
        <button type="button" @click="quick('month')">最近 30 天</button>
        <button type="button" @click="quick('this-month')">本月</button>
        <button type="button" @click="quick('all')">全部</button>
      </fieldset>
    </form>
    <p v-if="busy" role="status">正在查詢…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else>
      <p role="status">共 {{ reports.length }} 筆報告</p>
      <p v-if="!reports.length">此日期範圍沒有報告。</p>
      <ul v-else>
        <li v-for="report in reports" :key="report.report_id">
          <h2>{{ taipeiDateTime(report.generated_at) }}</h2>
          <p>
            綜合用藥／保健品分析：藥品 {{ report.drug_count }} 項、保健食品
            {{ report.product_count }} 項
          </p>
          <RouterLink :to="`/reports/${report.report_id}`">查看詳細資料 →</RouterLink>
        </li>
      </ul>
    </template>
  </main>
</template>
