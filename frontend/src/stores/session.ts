import { ref } from 'vue'
import { defineStore } from 'pinia'
import { getMe, loginWithGoogle, logout as logoutRequest, type Me } from '../api/auth'

export const useSessionStore = defineStore('session', () => {
  const me = ref<Me | null>(null)
  const loaded = ref(false)

  // 只在沒載入過時向後端查詢；查詢失敗（非 401）不標記為已載入，下次導頁會重試。
  async function load() {
    if (loaded.value) return
    me.value = await getMe()
    loaded.value = true
  }
  async function login(credential: string) {
    me.value = await loginWithGoogle(credential)
    loaded.value = true
    return me.value
  }
  async function logout() {
    await logoutRequest()
    me.value = null
    loaded.value = true
  }
  function markProfileCompleted() {
    if (me.value) me.value = { ...me.value, profile_completed: true }
  }

  return { me, loaded, load, login, logout, markProfileCompleted }
})
