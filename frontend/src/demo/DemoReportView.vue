<script setup lang="ts">
import ReportContent from '../components/ReportContent.vue'
import type { Report } from '../api/reports'
import example from '../../../docs/schemas/examples/08_report.json'
const report = example as Report
</script>

<template>
  <main>
    <h1>固定範例報告展示</h1>
    <p role="alert">
      <strong>示範資料，非實際個人化評估結果</strong
      >。以下是專案既有固定範例，與剛才輸入的藥名、成分及攝取量無關；未執行實際營養素或藥品交互作用計算，不可當作健康建議。
    </p>
    <ReportContent :report="report" />
  </main>
</template>
