<script setup lang="ts">
defineProps<{ exit: () => void }>()
</script>

<template>
  <section class="review-demo" aria-label="獨立示範測試流程">
    <div class="demo-label" role="status">
      <strong>示範資料，非實際個人化評估結果</strong>
      <button type="button" @click="exit">結束示範</button>
    </div>
    <aside class="demo-notice" role="status">
      <h1>人工校對示範測試模式</h1>
      <p><strong>示範資料，非實際個人化評估結果</strong></p>
      <p>
        以下載入既有樣本，未執行 OCR 或 AI
        辨識，也未附原始照片。所有編輯只保存在獨立示範區，不會送出產品、評估或報告請求。
      </p>
      <p>
        下一步只展示固定範例報告，不會計算實際營養素或藥品交互作用，也不是健康建議。一般流程中的資料保持原狀。
      </p>
      <button type="button" @click="exit">結束示範，返回一般流程</button>
    </aside>
    <RouterView />
  </section>
</template>

<style scoped>
.review-demo {
  font-size: 18px;
  line-height: 1.65;
}
.demo-label {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  color: white;
  background: var(--navy, #142332);
}
.demo-label button {
  background: white;
  color: var(--navy, #142332);
}
.demo-notice {
  padding: 24px;
  margin-bottom: 24px;
  border: 3px solid var(--navy, #142332);
  border-radius: 16px;
  background: var(--soft-lime, #f0f5e3);
}
button {
  min-height: 50px;
  font: inherit;
}
</style>
