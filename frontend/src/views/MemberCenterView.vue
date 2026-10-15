<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main>
    <h1>會員中心</h1>
    <p>目前可開啟設定表單，但儲存設定、記錄查詢與登出功能尚未開放。</p>

    <p>
      <RouterLink to="/settings">設定</RouterLink>
    </p>
    <p>
      <button type="button" disabled>記錄查詢（尚未開放）</button>
    </p>
    <p>
      <button type="button" disabled>登出（尚未開放）</button>
    </p>
  </main>
</template>
