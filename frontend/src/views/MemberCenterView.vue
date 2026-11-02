<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { errorMessage } from '../api/client'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const route = useRoute()
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
    <p v-if="route.query.profileSaved === '1'" role="status">基本資料已儲存。</p>
    <div v-if="session.me" class="member-welcome">
      <h2>歡迎回來{{ session.me.name?.trim() ? `，${session.me.name.trim()}` : '' }}！</h2>
      <p>在這裡管理您的基本資料，查看過去的評估記錄。</p>
    </div>

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
  </main>
</template>

<style scoped>
.member-welcome {
  margin-bottom: 28px;
}
.member-welcome h2 {
  font-size: clamp(24px, 3vw, 36px);
  margin-bottom: 12px;
  overflow-wrap: anywhere;
}
.member-welcome p {
  color: var(--muted);
  line-height: 1.7;
}
</style>
