<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GoogleLogin, type CallbackTypes } from 'vue3-google-login'
import { errorMessage } from '../api/client'
import { safeRedirect } from '../router/authGuard'
import { useSessionStore } from '../stores/session'

const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined
const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const message = ref('')

// Google 登入成功後，把憑證交給後端，再依健康資料是否填過導頁
const handleLoginSuccess: CallbackTypes.CredentialCallback = async (response) => {
  message.value = ''
  if (!response.credential) {
    message.value = '未取得 Google 登入憑證。'
    return
  }
  try {
    const me = await session.login(response.credential)
    const target = safeRedirect(route.query.redirect)
    await router.push(me.profile_completed ? target : { name: 'health-profile' })
  } catch (error) {
    message.value = errorMessage(error)
  }
}

const handleLoginError = () => {
  message.value = 'Google 登入失敗或已取消，請再試一次。'
}
</script>

<template>
  <main>
    <h1>登入</h1>
    <p id="login-notice">請使用 Google 帳號登入。第一次登入需再填寫基本健康資料。</p>
    <p v-if="!clientId" role="status">Google 登入尚未設定。</p>
    <div v-else class="google-login-container">
      <GoogleLogin :client-id="clientId" :callback="handleLoginSuccess" :error="handleLoginError" />
    </div>
    <p v-if="message" role="alert">{{ message }}</p>
  </main>
</template>
