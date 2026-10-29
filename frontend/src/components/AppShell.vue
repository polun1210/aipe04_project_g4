<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import UploadGuide from './UploadGuide.vue'

const route = useRoute()
const steps = [
  {
    name: 'medicine-upload',
    label: '藥包上傳',
    icon: 'M4 7h4l2-3h4l2 3h4v13H4Z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  },
  { name: 'medicine-review', label: '核對藥名', icon: 'M6 3h9l4 4v14H6Z M9 11h7 M9 15h7' },
  {
    name: 'supplement-upload',
    label: '保健食品上傳',
    icon: 'm8 16 8-8 M7 5a6 6 0 0 1 8 0l4 4a6 6 0 0 1-8 8l-4-4a6 6 0 0 1 0-8Z',
  },
  {
    name: 'supplement-review',
    label: '核對成分',
    icon: 'M13 21H5V3h10l4 4v5 M8 9h7 M8 13h3 M20 18a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M19 21l3 2',
  },
  { name: 'report', label: '評估報告', icon: 'M4 14h3v7H4Z M11 8h3v13h-3Z M18 3h3v18h-3Z' },
]
const activeStep = computed(() => steps.findIndex((step) => step.name === route.name))
const isAuth = computed(() => route.name === 'login' || route.name === 'register')
const isUpload = computed(
  () => route.name === 'medicine-upload' || route.name === 'supplement-upload',
)
const hasSidebar = computed(
  () => (!isAuth.value && activeStep.value === -1) || route.name === 'report',
)
const sidebarLinks = [
  { to: '/', label: '首頁', icon: 'M3 11 12 3l9 8 M5 10v11h14V10 M9 21v-7h6v7' },
  { to: '/medicine-upload', label: '上傳藥品照片', icon: steps[0]!.icon },
  { to: '/medicine-review', label: '確認藥品名稱', icon: steps[1]!.icon },
  { to: '/supplement-upload', label: '上傳保健食品標示', icon: steps[2]!.icon },
  { to: '/supplement-review', label: '確認成分與攝取量', icon: steps[3]!.icon },
  { to: '/reports', label: '查看評估報告', icon: steps[4]!.icon },
  {
    to: '/member-center',
    label: '會員中心',
    icon: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-3a8 8 0 0 1 16 0v3Z',
  },
]
</script>

<template>
  <div
    class="app-shell"
    :class="[
      { 'auth-layout': isAuth, 'with-sidebar': hasSidebar, 'upload-layout': isUpload },
      `route-${String(route.name)}`,
    ]"
  >
    <a class="shell-skip" href="#page-content">跳至主要內容</a>
    <header class="shell-header">
      <RouterLink to="/" class="shell-brand" aria-label="補藥亂吃！首頁"
        ><img src="/brand-mark.svg" width="48" height="48" alt="" /><span
          >補藥亂吃！</span
        ></RouterLink
      >
      <p class="shell-tagline">給長輩與照顧者的<br />AI 營養補充評估</p>
      <nav class="shell-account" aria-label="會員導覽">
        <template v-if="isAuth"
          ><RouterLink to="/register" class="shell-button secondary">註冊</RouterLink
          ><RouterLink to="/login" class="shell-button">登入</RouterLink></template
        >
        <template v-else
          ><RouterLink to="/member-center" class="account-link"
            ><svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-3a8 8 0 0 1 16 0v3Z" /></svg
            >會員中心</RouterLink
          ><span class="demo-badge">測試帳號</span></template
        >
      </nav>
    </header>

    <ol v-if="activeStep >= 0 && !hasSidebar" class="flow-steps" aria-label="評估流程">
      <li
        v-for="(step, index) in steps"
        :key="step.name"
        :class="{ current: index === activeStep, completed: index < activeStep }"
        :aria-current="index === activeStep ? 'step' : undefined"
      >
        <span class="flow-number">{{ String(index + 1).padStart(2, '0') }}</span
        ><svg viewBox="0 0 24 24" aria-hidden="true"><path :d="step.icon" /></svg
        ><span
          >{{ step.label
          }}<span v-if="index < activeStep" class="shell-sr-only">（先前步驟）</span></span
        >
      </li>
    </ol>

    <div class="shell-workspace">
      <aside v-if="hasSidebar" class="shell-sidebar">
        <p class="sidebar-label">我的補充管理</p>
        <nav aria-label="功能導覽">
          <RouterLink
            v-for="link in sidebarLinks"
            :key="link.to"
            :to="link.to"
            :class="{
              'is-report':
                link.to === '/reports' &&
                (route.name === 'report' || route.name === 'report-detail'),
            }"
            ><svg viewBox="0 0 24 24" aria-hidden="true"><path :d="link.icon" /></svg
            >{{ link.label }}</RouterLink
          >
        </nav>
        <div class="sidebar-note">
          <span>每一步，都由你確認。</span>
          <p>辨識結果核對完成後，<br />再進行補充資訊評估。</p>
        </div>
      </aside>
      <div id="page-content" class="page-view" tabindex="-1"><slot /></div>
      <UploadGuide v-if="isUpload" :supplement="route.name === 'supplement-upload'" />
    </div>

    <footer class="shell-footer">
      <RouterLink to="/">補藥亂吃！</RouterLink>
      <p>本工具提供補充安全檢查資訊，不取代醫師或藥師的專業建議。</p>
      <span>設計示意</span>
    </footer>
  </div>
</template>
