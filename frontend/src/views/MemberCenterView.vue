<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main>
    <h1>會員中心</h1>
    <p>目前使用後端測試帳號。登入、註冊、儲存設定與登出功能尚未開放。</p>

    <p>
      <RouterLink to="/settings">設定</RouterLink>
    </p>
    <p>
      <RouterLink to="/reports">記錄查詢</RouterLink>
    </p>
    <p>
      <button type="button" disabled>登出（尚未開放）</button>
    </p>
    <p><RouterLink to="/">回主頁</RouterLink></p>
  </main>
</template>
