<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { errorMessage } from '../api/client'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const session = useSessionStore()
const loggingOut = ref(false)
const error = ref('')

async function handleLogout() {
  if (loggingOut.value) return
  loggingOut.value = true
  error.value = ''
  try {
    await session.logout()
    await router.push('/')
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    loggingOut.value = false
  }
}
</script>

<template>
  <main>
    <h1>會員中心</h1>
    <p v-if="session.me">已登入：{{ session.me.name || session.me.email }}</p>

    <div class="member-actions">
      <RouterLink to="/settings"
        ><span aria-hidden="true">01</span><strong>個人資料設定 →</strong>
        <p>設定出生年月、性別與慢性疾病。</p></RouterLink
      >
      <RouterLink to="/reports"
        ><span aria-hidden="true">02</span><strong>評估記錄查詢 →</strong>
        <p>依日期查詢過去的營養補充評估報告。</p></RouterLink
      >
    </div>
    <p><RouterLink class="shell-button" to="/medicine-upload">開始新的評估 →</RouterLink></p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p>
      <button type="button" :disabled="loggingOut" @click="handleLogout">
        {{ loggingOut ? '登出中…' : '登出' }}
      </button>
    </p>
    <p><RouterLink to="/">回主頁</RouterLink></p>
  </main>
</template>
