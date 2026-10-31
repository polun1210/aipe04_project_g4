<script setup lang="ts">
defineProps<{ supplement: boolean }>()
const tips = [
  { number: '01', title: '完整標示入鏡', text: '保留完整藥名、成分與含量，讓 AI 更容易辨識。' },
  { number: '02', title: '避開反光與陰影', text: '在光線充足的地方拍攝，避免強烈反光遮住文字。' },
  { number: '03', title: '文字清楚不模糊', text: '保持畫面穩定，拍攝後先確認文字清晰可見。' },
]
</script>

<template>
  <aside class="upload-guide" aria-label="照片上傳指南">
    <div class="upload-story">
      <span class="story-kicker">從一張照片開始</span>
      <h2>
        拍下{{ supplement ? '標示' : '處方箋' }}，<br />讓 AI 幫你<br />整理{{
          supplement ? '成分' : '藥名'
        }}。
      </h2>
      <p>辨識完成後，由你核對，<br />再一起了解補充搭配。</p>
      <div class="story-art" aria-hidden="true">
        <svg viewBox="0 0 160 140">
          <rect
            x="39"
            y="10"
            width="82"
            height="120"
            rx="13"
            fill="#f3f4f2"
            stroke="#142332"
            stroke-width="4"
          />
          <path d="M66 18h28" stroke="#142332" stroke-width="5" stroke-linecap="round" />
          <rect x="51" y="36" width="58" height="69" rx="6" fill="#d4e887" />
          <path
            d="m65 77 12 11 20-27"
            fill="none"
            stroke="#142332"
            stroke-width="5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M17 48 7 41m11 29H4m139-22 10-7m-11 29h14"
            stroke="#d4e887"
            stroke-width="3"
            stroke-linecap="round"
          />
        </svg>
      </div>
    </div>
    <section class="photo-tips">
      <h2>拍照小技巧</h2>
      <ol>
        <li v-for="tip in tips" :key="tip.number">
          <span>{{ tip.number }}</span>
          <div>
            <h3>{{ tip.title }}</h3>
            <p>{{ tip.text }}</p>
          </div>
        </li>
      </ol>
    </section>
    <p class="guide-privacy">上傳前，記得遮住姓名等不必要的個人資訊。</p>
  </aside>
</template>
