<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main>
    <h1>會員中心</h1>
    <p>目前使用後端測試帳號。登入、註冊、儲存設定與登出功能尚未開放。</p>

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
    <p>
      <button type="button" disabled>登出（尚未開放）</button>
    </p>
    <p><RouterLink to="/">回主頁</RouterLink></p>
  </main>
</template>
