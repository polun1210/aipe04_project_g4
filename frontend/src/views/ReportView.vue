<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { createReport, getReport, type Report } from '../api/reports'
import { errorMessage } from '../api/client'
import ReportContent from '../components/ReportContent.vue'
const route = useRoute()
const report = ref<Report | null>(null)
const error = ref('')
const busy = ref(false)
let request = 0
async function load() {
  const current = ++request
  busy.value = true
  error.value = ''
  report.value = null
  try {
    const result =
      route.name === 'report-detail'
        ? await getReport(String(route.params.reportId))
        : await createReport(String(route.params.caseId))
    if (current === request) report.value = result
  } catch (reason) {
    if (current === request) error.value = errorMessage(reason)
  } finally {
    if (current === request) busy.value = false
  }
}
function printReport() {
  window.print()
}
watch(() => route.fullPath, load, { immediate: true })
</script>
<template>
  <main>
    <p class="no-print">
      <RouterLink v-if="route.name === 'report-detail'" to="/reports">← 返回報告記錄查詢</RouterLink
      ><RouterLink v-else to="/">回主頁</RouterLink>
    </p>
    <p v-if="busy" role="status">正在載入報告…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" class="no-print" type="button" @click="load">重試</button>
    <ReportContent v-if="report" :report="report" />
    <button v-if="report" class="no-print" type="button" @click="printReport">列印／另存 PDF</button>
    <p v-if="report" class="no-print">在瀏覽器列印視窗選擇「另存為 PDF」。</p>
    <p class="no-print"><RouterLink to="/reports">查看報告記錄</RouterLink></p>
  </main>
</template>

<style scoped>
@media print {
  .no-print {
    display: none !important;
  }
}
</style>
