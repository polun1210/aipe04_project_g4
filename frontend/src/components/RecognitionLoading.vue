<template>
  <div class="recognition-loading" role="status" aria-live="polite" aria-atomic="true">
    <svg class="recognition-art" viewBox="0 0 320 240" aria-hidden="true" focusable="false">
      <g class="recognition-document">
        <path d="M202 28H104a16 16 0 0 0-16 16v164a16 16 0 0 0 16 16h120V54Z" />
        <path d="M202 28v26h22M114 80h70M114 105h88M114 130h50M114 155h50" />
      </g>
      <g class="recognition-magnifier">
        <circle cx="216" cy="155" r="43" />
        <path d="m247 186 26 26" />
      </g>
    </svg>
    <p class="recognition-title">辨識中…</p>
    <p class="recognition-description">正在讀取照片中的資訊…</p>
  </div>
</template>

<style scoped>
.recognition-loading[role='status']:not(:empty) {
  --recognition-background: var(--navy, #142332);
  --recognition-document: var(--white, #fff);
  --recognition-accent: var(--lime, #d4e887);
  position: fixed;
  z-index: 1000;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  box-sizing: border-box;
  width: min(420px, calc(100% - 32px));
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
  display: grid;
  justify-items: center;
  gap: 8px;
  margin: 0;
  padding: 24px 16px 32px;
  border-radius: 24px;
  background: var(--recognition-background);
  box-shadow: 0 16px 64px #14233255;
  color: var(--recognition-document);
  text-align: center;
}

.recognition-loading .recognition-art {
  display: block;
  width: min(100%, 280px);
  height: auto;
  fill: none;
  stroke: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.recognition-document {
  fill: none;
  stroke: var(--recognition-document);
  stroke-width: 9px;
}

.recognition-magnifier {
  stroke: var(--recognition-accent);
  stroke-width: 10px;
  animation: recognition-patrol 2.5s ease-in-out infinite;
}

.recognition-magnifier circle {
  fill: var(--recognition-background);
}

.recognition-magnifier path {
  stroke-width: 18px;
}

.recognition-loading .recognition-title {
  margin: 0;
  color: var(--recognition-document);
  font-size: clamp(24px, 3vw, 30px);
  font-weight: 800;
  line-height: 1.5;
}

.recognition-loading .recognition-description {
  margin: 0;
  color: var(--recognition-accent);
  font-size: clamp(18px, 2.5vw, 22px);
  line-height: 1.6;
}

@keyframes recognition-patrol {
  0%,
  100% {
    transform: translate(0, 0);
  }
  35% {
    transform: translate(-8px, -12px);
  }
  70% {
    transform: translate(4px, 6px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .recognition-magnifier {
    animation: none;
  }
}
</style>
