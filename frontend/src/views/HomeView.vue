<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <header>
    <RouterLink to="/">補對了嗎?</RouterLink>

    <nav aria-label="會員導覽">
      <button type="button" disabled>註冊（尚未開放）</button>
      <button type="button" disabled>登入（尚未開放）</button>
    </nav>
  </header>

  <main>
    <section aria-labelledby="welcome-title">
      <h1 id="welcome-title">歡迎使用保健食品評估系統</h1>
      <p>協助使用者了解保健食品與用藥資訊。</p>

      <!-- 未來連接藥圖片上傳頁，目前尚未建立對應路由。 -->
      <button type="button" disabled>開始使用（尚未開放）</button>
    </section>

    <section aria-labelledby="guide-title">
      <h2 id="guide-title">操作手冊／使用指南</h2>

      <ol>
        <li>
          <h3>步驟 1：上傳並核對藥品</h3>
          <p>步驟 1 範例圖（待補）</p>
          <p>上傳藥包圖片，辨識完成後確認藥品資料。</p>
        </li>
        <li>
          <h3>步驟 2：上傳並核對保健食品</h3>
          <p>步驟 2 範例圖（待補）</p>
          <p>上傳保健食品圖片，確認成分並填寫實際服用方式。</p>
        </li>
        <li>
          <h3>步驟 3：查看評估報告</h3>
          <p>步驟 3 範例圖（待補）</p>
          <p>查看評估結果與改善建議。</p>
        </li>
      </ol>
    </section>
  </main>
</template>
