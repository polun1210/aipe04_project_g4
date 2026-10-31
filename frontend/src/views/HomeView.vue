<script setup lang="ts">
import { RouterLink } from 'vue-router'
const heroImage = `${import.meta.env.BASE_URL}home-supplements.webp`
const steps = [
  {
    number: '01',
    title: '核對藥品',
    text: '上傳處方箋或藥品照片，辨識後由你核對藥品名稱與實際服用情況。',
  },
  { number: '02', title: '核對保健食品', text: '上傳保健食品標示照片，辨識成分並確認實際攝取量。' },
  {
    number: '03',
    title: '查看評估報告',
    text: '綜合你的藥品與保健食品資料，提供攝取上限與可能的交互作用提醒。',
  },
]
</script>

<template>
  <div class="home-page">
    <a class="skip-link" href="#home-main">跳至主要內容</a>
    <header class="site-header">
      <RouterLink class="brand" to="/" aria-label="補藥亂吃！首頁"
        ><span class="brand-mark" aria-hidden="true"></span><span>補藥亂吃！</span></RouterLink
      >
      <p class="brand-description">台灣長輩與家人的 AI 營養補充評估工具</p>
      <nav class="account-nav" aria-label="會員導覽">
        <RouterLink class="button button-outline" to="/register">註冊</RouterLink>
        <RouterLink class="button button-lime" to="/login">登入</RouterLink>
      </nav>
    </header>
    <main id="home-main" tabindex="-1">
      <section class="hero" aria-labelledby="hero-title">
        <div class="hero-visual">
          <img
            :src="heroImage"
            alt="日光下的木桌上，整齊擺放保健食品瓶、處方箋與一杯水"
            width="1536"
            height="1024"
            fetchpriority="high"
          />
          <div class="visual-note" aria-hidden="true">
            <span class="note-index">DAILY CARE / 日常照顧</span>
            <p>日常的藥物<br />與保健食品，<br />一起更安心。</p>
            <span class="note-line"></span>
          </div>
        </div>
        <div class="hero-content">
          <span class="eyebrow"><span></span>給自己，也給在乎的人</span>
          <h1 id="hero-title">補充之前，<br />先<span>了解你的搭配。</span></h1>
          <p class="hero-description">
            上傳處方箋與保健食品照片，<br class="tablet-break" />了解攝取上限與用藥交互作用。
          </p>
          <RouterLink class="button start-button" to="/medicine-upload"
            >開始使用<svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              aria-hidden="true"
            >
              <path d="M4 12h16m-7-7 7 7-7 7" /></svg
          ></RouterLink>
          <p class="verification-note">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              aria-hidden="true"
            >
              <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
              <path d="m8 12 3 3 5-6" /></svg
            >辨識後，由你核對資料再評估
          </p>
        </div>
      </section>
      <section class="guide" aria-labelledby="guide-title">
        <div class="guide-heading">
          <h2 id="guide-title">三個步驟，讓補充更有依據</h2>
          <span>從照片開始，一步步了解</span>
        </div>
        <ol class="steps">
          <li v-for="(step, index) in steps" :key="step.number" class="step-card">
            <div class="step-copy">
              <span class="step-number" aria-hidden="true">{{ step.number }}</span>
              <h3>
                <span class="sr-only">步驟 {{ index + 1 }}：</span>{{ step.title }}
              </h3>
              <p>{{ step.text }}</p>
            </div>
            <svg class="step-art" viewBox="0 0 200 220" fill="none" aria-hidden="true">
              <path
                d="M47 27C92-1 176 25 185 89c14 88-44 129-105 106C15 172 8 69 47 27Z"
                fill="var(--soft-lime)"
              />
              <g v-if="index === 0">
                <rect
                  x="51"
                  y="25"
                  width="116"
                  height="174"
                  rx="15"
                  fill="var(--white)"
                  stroke="currentColor"
                  stroke-width="3.5"
                />
                <path d="M88 26h42l-4 8H92Z" fill="currentColor" />
                <rect x="65" y="48" width="88" height="126" rx="9" fill="var(--pale)" />
                <g transform="rotate(-19 110 110)" stroke="currentColor" stroke-width="2.5">
                  <rect x="80" y="63" width="57" height="99" rx="10" fill="var(--white)" />
                  <rect x="88" y="74" width="13" height="31" rx="6.5" fill="var(--pale)" />
                  <rect x="115" y="74" width="13" height="31" rx="6.5" fill="var(--pale)" />
                  <rect x="88" y="120" width="13" height="31" rx="6.5" fill="var(--pale)" />
                  <rect x="115" y="120" width="13" height="31" rx="6.5" fill="var(--pale)" />
                </g>
                <path
                  d="m32 41-12-10m9 31H13m19 20L20 94"
                  stroke="currentColor"
                  stroke-width="3"
                  stroke-linecap="round"
                />
              </g>
              <g v-else-if="index === 1">
                <rect
                  x="119"
                  y="43"
                  width="68"
                  height="85"
                  rx="7"
                  fill="var(--white)"
                  stroke="currentColor"
                  stroke-width="3"
                />
                <path
                  d="M132 60h40m-40 12h40m-40 12h28m-28 12h35m-35 12h16"
                  stroke="var(--muted)"
                  stroke-width="3.5"
                  stroke-linecap="round"
                />
                <path
                  d="M48 65h44v13c0 7 15 10 15 29v65c0 22-75 22-75 0v-65c0-19 16-22 16-29Z"
                  fill="currentColor"
                />
                <path d="M35 104c20 8 48 8 69 0v61c-20 8-48 8-69 0Z" fill="var(--white)" />
                <rect
                  x="41"
                  y="44"
                  width="58"
                  height="28"
                  rx="5"
                  fill="var(--white)"
                  stroke="currentColor"
                  stroke-width="3"
                />
                <path
                  d="M42 52h56M47 121h43m-43 11h43m-43 11h24"
                  stroke="var(--muted)"
                  stroke-width="3.5"
                  stroke-linecap="round"
                />
                <path
                  d="M72 163c-13-1-16-9-14-16 10 0 15 6 14 16Zm2 0c-3-13 1-21 13-23 1 12-3 20-13 23Z"
                  fill="var(--leaf)"
                />
              </g>
              <g v-else>
                <rect
                  x="39"
                  y="29"
                  width="116"
                  height="167"
                  rx="9"
                  fill="var(--white)"
                  stroke="currentColor"
                  stroke-width="3.5"
                />
                <path
                  d="M59 49h67M59 61h39"
                  stroke="currentColor"
                  stroke-width="4"
                  stroke-linecap="round"
                />
                <path
                  d="M59 77h75M59 87h68M59 97h38M59 160h75M59 170h67M59 180h47"
                  stroke="var(--muted)"
                  stroke-width="3"
                  stroke-linecap="round"
                />
                <path
                  d="M59 115h21m-21 20h16"
                  stroke="currentColor"
                  stroke-width="4"
                  stroke-linecap="round"
                />
                <rect x="101" y="127" width="9" height="19" rx="1" fill="currentColor" />
                <rect x="116" y="116" width="9" height="30" rx="1" fill="currentColor" />
                <rect x="131" y="106" width="9" height="40" rx="1" fill="var(--leaf)" />
              </g>
              <circle
                cx="163"
                cy="172"
                r="22"
                fill="var(--lime)"
                stroke="currentColor"
                stroke-width="3.5"
              />
              <path
                d="m152 172 7 7 14-16"
                stroke="currentColor"
                stroke-width="3.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </li>
        </ol>
      </section>
    </main>
    <footer class="site-footer">
      <RouterLink class="brand footer-brand" to="/"
        ><span class="brand-mark" aria-hidden="true"></span><span>補藥亂吃！</span></RouterLink
      >
      <p>本工具提供補充安全檢查資訊，不取代醫師或藥師的專業建議。</p>
    </footer>
  </div>
</template>

<style scoped>
:global(body:has(.home-page)) {
  margin: 0;
  background: #f3f4f2;
}
.home-page {
  --navy: #142332;
  --lime: #d4e887;
  --soft-lime: #f0f5e3;
  --white: #fff;
  --pale: #e9edee;
  --muted: #77828a;
  --leaf: #a7c74c;
  box-sizing: border-box;
  max-width: 1600px;
  margin: auto;
  padding: 24px 32px 20px;
  color: var(--navy);
  font-family: 'Noto Sans TC', 'Microsoft JhengHei', sans-serif;
  -webkit-font-smoothing: antialiased;
}
.home-page *,
.home-page *::before,
.home-page *::after {
  box-sizing: border-box;
}
a {
  color: inherit;
  text-decoration: none;
}
a:focus-visible {
  outline: 3px solid #537417;
  outline-offset: 5px;
}
.skip-link {
  position: absolute;
  top: -80px;
  left: 32px;
  z-index: 10;
  padding: 16px 24px;
  background: var(--lime);
  border: 2px solid var(--navy);
  border-radius: 10px;
}
.skip-link:focus {
  top: 8px;
}
.site-header {
  display: flex;
  align-items: center;
  gap: 24px;
  min-height: 82px;
  border: 2px solid var(--navy);
  border-radius: 22px;
  padding: 12px 22px 12px 26px;
  margin-bottom: 20px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  font-size: 34px;
  font-weight: 900;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.brand-mark {
  display: block;
  position: relative;
  width: 48px;
  height: 48px;
  border-radius: 13px;
  background: var(--navy);
}
.brand-mark::before,
.brand-mark::after {
  content: '';
  position: absolute;
  inset: 12px 20px;
  border-radius: 3px;
  background: var(--white);
}
.brand-mark::after {
  inset: 20px 12px;
}
.brand-description {
  margin: 0;
  border-left: 1px solid var(--muted);
  padding-left: 24px;
  font-size: 17px;
  letter-spacing: 0.04em;
  line-height: 1.6;
}
.account-nav {
  display: flex;
  gap: 14px;
  margin-left: auto;
}
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 48px;
  padding: 10px 32px;
  border: 2px solid transparent;
  border-radius: 13px;
  font-size: 18px;
  font-weight: 800;
  transition:
    background-color 180ms ease,
    box-shadow 180ms ease;
}
.button-outline {
  border-color: var(--navy);
  background: var(--white);
}
.button-outline:hover {
  background: var(--pale);
}
.button-lime,
.start-button {
  background: var(--lime);
}
.button-lime:hover,
.start-button:hover {
  background: #c3dc68;
  box-shadow: 0 4px 0 #14233225;
}
.button:active {
  box-shadow: inset 0 0 0 2px var(--navy);
}
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 24px;
  min-height: 495px;
  background: var(--navy);
}
.hero-visual {
  position: absolute;
  inset: 0 0 0 43%;
}
.hero-visual img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 57% center;
  display: block;
}
.visual-note {
  position: absolute;
  right: 24px;
  top: 28px;
  padding: 22px;
  border-radius: 19px;
  background: var(--lime);
}
.note-index {
  font-size: 10px;
  letter-spacing: 0.07em;
  font-weight: 700;
}
.visual-note p {
  font-size: 23px;
  font-weight: 800;
  line-height: 1.5;
  margin: 12px 0 20px;
}
.note-line {
  display: block;
  height: 3px;
  width: 40px;
  background: var(--navy);
  border-radius: 3px;
}
.image-caption {
  position: absolute;
  right: 20px;
  bottom: 14px;
  padding: 4px 9px;
  font-size: 12px;
  border-radius: 5px;
  background: #ffffffde;
}
.hero-content {
  position: relative;
  width: 57%;
  min-height: 495px;
  padding: 36px 40px 26px;
  color: var(--white);
  background: var(--navy);
  clip-path: polygon(0 0, 100% 0, 89% 100%, 0 100%);
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 14px;
  letter-spacing: 0.09em;
  color: #dce3e7;
}
.eyebrow > span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--lime);
}
h1 {
  margin: 27px 0 20px;
  font-size: clamp(40px, 4.3vw, 66px);
  font-weight: 900;
  letter-spacing: -0.035em;
  line-height: 1.3;
}
h1 span {
  color: var(--lime);
}
.hero-description {
  max-width: 93%;
  font-size: 20px;
  line-height: 1.7;
  margin: 0 0 27px;
  color: #e0e5e9;
}
.tablet-break {
  display: none;
}
.start-button {
  min-height: 72px;
  min-width: 310px;
  border-radius: 23px;
  color: var(--navy);
  font-size: 30px;
  gap: 30px;
}
.start-button svg {
  width: 32px;
  height: 32px;
}
.verification-note {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 0 0;
  font-size: 17px;
  color: #dce3e7;
}
.verification-note svg {
  height: 20px;
  width: 20px;
}
.concept-label {
  display: block;
  margin-top: 17px;
  font-size: 12px;
  color: #bdc8cf;
}
.guide {
  margin-top: 24px;
}
.guide-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 2px 12px;
}
.guide-heading h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.guide-heading > span {
  font-size: 13px;
  color: #53616c;
}
.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 16px;
}
.step-card {
  position: relative;
  min-height: 258px;
  overflow: hidden;
  padding: 15px 24px 22px;
  background: #fcfdfb;
  border: 2px solid var(--navy);
  border-radius: 20px;
}
.step-copy {
  position: relative;
  z-index: 1;
}
.step-number {
  font-size: 80px;
  font-weight: 900;
  line-height: 1.1;
  letter-spacing: -0.06em;
}
.step-card h3 {
  margin: 2px 0 12px;
  font-size: clamp(22px, 2.1vw, 30px);
  font-weight: 900;
  letter-spacing: -0.04em;
}
.step-card p {
  max-width: 61%;
  margin: 0;
  font-size: 17px;
  line-height: 1.65;
}
.step-art {
  position: absolute;
  right: 4px;
  top: 32px;
  width: 42%;
  height: 210px;
}
.site-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-top: 20px;
  padding: 16px 28px;
  min-height: 68px;
  border-radius: 18px;
  background: var(--navy);
  color: var(--white);
}
.footer-brand {
  font-size: 22px;
  gap: 12px;
}
.footer-brand .brand-mark {
  width: 34px;
  height: 34px;
  background: var(--white);
  border-radius: 8px;
}
.footer-brand .brand-mark::before {
  inset: 8px 14px;
  background: var(--navy);
  border-radius: 2px;
}
.footer-brand .brand-mark::after {
  inset: 14px 8px;
  background: var(--navy);
  border-radius: 2px;
}
.site-footer p {
  margin: 0;
  font-size: 14px;
  color: #d0d9df;
  line-height: 1.7;
}
.sr-only {
  position: absolute;
  height: 1px;
  width: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
@media (min-width: 1440px) {
  .hero-content {
    padding: 36px 44px 30px;
  }
  .hero-description {
    font-size: 22px;
  }
  .step-card {
    min-height: 274px;
  }
  .step-card p {
    font-size: 19px;
  }
  .step-number {
    font-size: 88px;
  }
  .step-art {
    height: 230px;
    top: 26px;
  }
}
@media (max-width: 1150px) {
  .home-page {
    padding: 20px;
  }
  .brand {
    font-size: 28px;
    gap: 12px;
  }
  .site-header {
    gap: 18px;
    padding: 12px 18px;
  }
  .brand-description {
    font-size: 14px;
    padding-left: 18px;
    max-width: 255px;
  }
  .button {
    padding-inline: 24px;
  }
  .hero-content {
    width: 61%;
    padding: 32px;
  }
  .hero-description {
    font-size: 18px;
  }
  .hero-visual {
    left: 45%;
  }
  .visual-note {
    padding: 18px;
    right: 18px;
  }
  .visual-note p {
    font-size: 20px;
  }
  .step-card {
    padding: 18px;
    min-height: 285px;
  }
  .step-art {
    width: 40%;
    height: 165px;
    top: 35px;
  }
  .step-card p {
    font-size: 17px;
  }
  .step-card h3 {
    margin-top: 8px;
  }
  .step-number {
    font-size: 72px;
  }
}
@media (max-width: 850px) {
  .brand-description {
    display: none;
  }
  .hero-content {
    width: 66%;
  }
  .hero-visual {
    left: 44%;
  }
  h1 {
    font-size: 42px;
  }
  .tablet-break {
    display: block;
  }
  .visual-note {
    top: 22px;
    right: 16px;
    padding: 16px;
  }
  .note-index {
    display: none;
  }
  .visual-note p {
    font-size: 18px;
    margin-top: 0;
  }
  .start-button {
    min-width: 260px;
  }
  .steps {
    gap: 12px;
  }
  .step-card {
    padding: 16px;
    min-height: 360px;
  }
  .step-art {
    top: auto;
    bottom: 8px;
    right: 8px;
    height: 130px;
    width: 55%;
  }
  .step-card h3 {
    font-size: 22px;
  }
  .step-card p {
    font-size: 17px;
    max-width: 100%;
  }
  .site-footer {
    align-items: flex-start;
    padding: 20px;
  }
  .site-footer p {
    max-width: 360px;
  }
}
@media (max-width: 600px) {
  .home-page {
    padding: 12px;
  }
  .site-header {
    border-radius: 16px;
    min-height: 72px;
    margin-bottom: 12px;
    gap: 10px;
    padding: 12px;
    flex-wrap: wrap;
  }
  .brand {
    font-size: 23px;
    gap: 9px;
  }
  .brand-mark {
    width: 36px;
    height: 36px;
    border-radius: 10px;
  }
  .brand-mark::before {
    inset: 9px 15px;
  }
  .brand-mark::after {
    inset: 15px 9px;
  }
  .account-nav {
    gap: 8px;
  }
  .account-nav .button {
    min-height: 44px;
    padding: 8px 12px;
    font-size: 16px;
    border-radius: 10px;
  }
  .hero {
    display: flex;
    flex-direction: column;
    border-radius: 18px;
  }
  .hero-content {
    width: 100%;
    min-height: auto;
    padding: 28px 24px;
    clip-path: none;
    order: -1;
  }
  h1 {
    font-size: clamp(32px, 8vw, 46px);
    margin: 23px 0 18px;
  }
  .eyebrow {
    font-size: 13px;
  }
  .hero-description {
    font-size: 18px;
    max-width: 100%;
    margin-bottom: 24px;
  }
  .tablet-break {
    display: none;
  }
  .start-button {
    display: flex;
    min-width: 0;
    width: 100%;
    min-height: 64px;
    border-radius: 18px;
    font-size: 26px;
  }
  .verification-note {
    font-size: 15px;
    justify-content: center;
  }
  .concept-label {
    text-align: center;
    margin-top: 14px;
    font-size: 12px;
  }
  .hero-visual {
    position: relative;
    inset: auto;
    height: 270px;
  }
  .hero-visual img {
    object-position: center 60%;
  }
  .visual-note {
    top: 16px;
    right: 16px;
    border-radius: 13px;
    padding: 14px;
  }
  .visual-note p {
    font-size: 16px;
    margin-bottom: 12px;
  }
  .note-line {
    width: 28px;
    height: 2px;
  }
  .image-caption {
    bottom: 10px;
    right: 12px;
  }
  .guide {
    margin-top: 24px;
  }
  .guide-heading {
    margin: 0 4px 14px;
  }
  .guide-heading h2 {
    font-size: 17px;
  }
  .guide-heading > span {
    display: none;
  }
  .steps {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .step-card {
    min-height: 238px;
    padding: 18px 22px;
    border-radius: 18px;
  }
  .step-number {
    font-size: 66px;
  }
  .step-card h3 {
    font-size: 25px;
    margin: 2px 0 10px;
  }
  .step-card p {
    font-size: 17px;
    max-width: 62%;
  }
  .step-art {
    top: 20px;
    bottom: auto;
    height: 200px;
    width: 40%;
    right: 3px;
  }
  .site-footer {
    flex-direction: column;
    gap: 14px;
    margin-top: 16px;
    border-radius: 16px;
    padding: 22px;
  }
  .footer-brand {
    font-size: 22px;
  }
  .site-footer p {
    font-size: 14px;
    max-width: none;
  }
}
@media (max-width: 370px) {
  .brand {
    font-size: 21px;
  }
  .account-nav .button {
    padding-inline: 10px;
  }
  .site-header {
    gap: 8px;
  }
  .hero-content {
    padding-inline: 20px;
  }
  .step-card {
    padding-inline: 18px;
  }
  .step-art {
    width: 38%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .button {
    transition: none;
  }
}
</style>
