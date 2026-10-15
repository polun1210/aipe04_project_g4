<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

const email = ref<string>('')
const password = ref<string>('')

function handleSubmit(): void {
  // 暫不執行登入動作；保留函式供學習表單事件。
  return
}
</script>

<template>
  <header>
    <RouterLink to="/">補對了嗎?</RouterLink>
  </header>

  <main>
    <h1>登入</h1>
    <p id="login-notice">目前可開啟註冊表單，但登入與建立帳號功能尚未開放。</p>

    <!-- @submit：Vue 語法，監聽表單送出事件。
    .prevent：阻止瀏覽器原本的表單送出行為，避免重新載入頁面。
    "handleSubmit"：事件發生時執行的函式。 -->
    <form aria-describedby="login-notice" @submit.prevent="handleSubmit">
      <p>
        <!-- v-model="email" 提供雙向綁定 -->
        <label for="email">帳號（Email）</label>
        <input id="email" v-model="email" type="email" autocomplete="username" />
      </p>

      <p>
        <label for="password">密碼</label>
        <input
          id="password"
          v-model="password"
          type="password"
          autocomplete="current-password"
        />
      </p>

      <RouterLink to="/register">註冊</RouterLink>
      <button type="submit" disabled>登入（尚未開放）</button>
    </form>
  </main>
</template>
