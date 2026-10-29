<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { GoogleLogin, type CallbackTypes } from 'vue3-google-login'

// 想修改頁面標題，改這行文字即可
const title = '歡迎使用，請選擇以下方式登入'

const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
const message = ref('')
const isCheckingSession = ref(true)

type User = {
  user_id: number
  email: string | null
  name: string | null
}

const currentUser = ref<User | null>(null)

// 頁面開啟或重新整理時，向後端確認是否已登入
onMounted(async () => {
  try {
    const res = await fetch('http://localhost:8000/api/me', {
      credentials: 'include',
    })

    if (res.ok) {
      currentUser.value = await res.json()
    }
  } catch (error) {
    console.error('查詢登入狀態失敗：', error)
  } finally {
    isCheckingSession.value = false
  }
})

// Google 登入成功後，把憑證交給後端
const handleLoginSuccess: CallbackTypes.CredentialCallback = async (response) => {
  const credential = response.credential

  if (!credential) {
    message.value = '未取得 Google 登入憑證。'
    return
  }

  try {
    const res = await fetch('http://localhost:8000/api/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ credential }),
    })

    if (!res.ok) {
      throw new Error(`登入失敗：${res.status}`)
    }

    const user: User = await res.json()
    currentUser.value = user
    message.value = `登入成功：${user.email}`
  } catch (error) {
    console.error('後端驗證失敗：', error)
    message.value = '後端驗證失敗，請稍後再試。'
  }
}

const handleLoginError = (error: unknown) => {
  console.error('Google 登入失敗：', error)
  message.value = 'Google 登入失敗或已取消，請再試一次。'
}

// 登出並清除畫面上的使用者資料
async function handleLogout() {
  try {
    const res = await fetch('http://localhost:8000/api/logout', {
      method: 'POST',
      credentials: 'include',
    })

    if (!res.ok) {
      throw new Error(`登出失敗：${res.status}`)
    }

    currentUser.value = null
    message.value = '已登出'
  } catch (error) {
    console.error('登出失敗：', error)
    message.value = '登出失敗，請稍後再試。'
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <h1>{{ title }}</h1>

      <p v-if="isCheckingSession">正在確認登入狀態…</p>

      <div v-else-if="currentUser" class="user-info">
        <p>已登入：{{ currentUser.name || currentUser.email }}</p>
        <button type="button" @click="handleLogout">登出</button>
      </div>

      <div v-else class="google-login-container">
        <GoogleLogin
          :client-id="clientId"
          :callback="handleLoginSuccess"
          :error="handleLoginError"
        />
      </div>

      <p v-if="message" role="status">{{ message }}</p>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.login-card {
  width: min(100%, 400px);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

h1 {
  margin: 0;
}

.google-login-container,
.user-info {
  margin-top: 8px;
}
</style>