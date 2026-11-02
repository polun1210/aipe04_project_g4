<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
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
const GOOGLE_BUTTON_SCALE = 1.6
const googleButtonContainer = ref<HTMLElement | null>(null)
const googleButtonWidth = ref(0)
let resizeObserver: ResizeObserver | undefined

onMounted(() => {
  if (!googleButtonContainer.value) return
  resizeObserver = new ResizeObserver(([entry]) => {
    if (entry && entry.contentRect.width > 0) {
      // 預留整顆按鈕等比例放大後的空間，包含 Google iframe 的文字與圖示。
      googleButtonWidth.value = Math.floor(
        Math.min(360, entry.contentRect.width) / GOOGLE_BUTTON_SCALE,
      )
    }
  })
  resizeObserver.observe(googleButtonContainer.value)
})
onUnmounted(() => resizeObserver?.disconnect())

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
    <div
      v-else
      ref="googleButtonContainer"
      class="google-login-container"
      :style="{ '--google-button-scale': GOOGLE_BUTTON_SCALE }"
    >
      <GoogleLogin
        v-if="googleButtonWidth > 0"
        :key="googleButtonWidth"
        class="google-login-button"
        :client-id="clientId"
        :button-config="{
          theme: 'outline',
          size: 'large',
          shape: 'pill',
          text: 'signin_with',
          locale: 'zh-TW',
          width: String(googleButtonWidth),
        }"
        :callback="handleLoginSuccess"
        :error="handleLoginError"
      />
    </div>
    <p v-if="message" role="alert">{{ message }}</p>
  </main>
</template>

<style scoped>
.google-login-container {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 56px;
  margin: 28px 0 20px;
}
.google-login-button {
  /* zoom 同步放大官方按鈕與點擊範圍，並讓版面保留放大後的空間。 */
  zoom: var(--google-button-scale);
}
</style>
