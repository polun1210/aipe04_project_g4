<script setup lang="ts">
import { ref } from 'vue'
import { askReport, type ChatTurn } from '../api/reports'
import { ApiError } from '../api/client'

const props = defineProps<{ reportId: string }>()
const presets = [
  '哪些項目超過上限？',
  '哪些項目需要問醫師或藥師？',
  '哪些產品要錯開時間吃？',
  '報告最重要的重點是什麼？',
]
const MAX_QUESTION = 500
const MAX_TURNS = 10 // 與後端上限一致：5 輪問答，超過丟掉最舊的
const turns = ref<ChatTurn[]>([])
const draft = ref('')
const error = ref('')
const busy = ref(false)

async function ask(raw: string) {
  const question = raw.trim()
  if (busy.value) return
  if (!question) {
    error.value = '請先輸入問題'
    return
  }
  if (question.length > MAX_QUESTION) {
    error.value = `問題請在 ${MAX_QUESTION} 字以內`
    return
  }
  error.value = ''
  busy.value = true
  try {
    const result = await askReport(props.reportId, question, turns.value)
    const next: ChatTurn[] = [
      ...turns.value,
      { role: 'user', content: question },
      { role: 'assistant', content: result.answer },
    ]
    turns.value = next.slice(-MAX_TURNS)
    draft.value = ''
  } catch (reason) {
    error.value =
      reason instanceof ApiError && reason.body.error.code === 'chat_disabled'
        ? '對話功能未啟用'
        : '目前無法回答'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="report-chat no-print" aria-labelledby="report-chat-title">
    <h2 id="report-chat-title">問這份報告</h2>
    <p class="report-chat-notice">此回答由 AI 依報告內容產生，不能取代醫師或藥師</p>
    <div class="report-chat-presets">
      <button v-for="q in presets" :key="q" type="button" :disabled="busy" @click="ask(q)">
        {{ q }}
      </button>
    </div>
    <ol v-if="turns.length" class="report-chat-log">
      <li
        v-for="(turn, i) in turns"
        :key="i"
        :class="turn.role === 'user' ? 'report-chat-question' : 'report-chat-answer'"
      >
        {{ turn.content }}
      </li>
    </ol>
    <p v-if="busy" role="status">正在回答…</p>
    <form class="report-chat-form" @submit.prevent="ask(draft)">
      <label class="report-chat-label" for="report-chat-input">輸入你的問題</label>
      <textarea
        id="report-chat-input"
        v-model="draft"
        rows="2"
        :maxlength="MAX_QUESTION"
        placeholder="例如：魚油可以和降血壓藥一起吃嗎？"
      />
      <button type="submit" :disabled="busy">送出</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.report-chat {
  margin-top: 24px;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--white);
}
.report-chat-notice {
  color: var(--muted);
}
.report-chat-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.report-chat-log {
  display: grid;
  gap: 8px;
  margin: 12px 0;
  padding: 0;
  list-style: none;
}
.report-chat-form {
  display: grid;
  gap: 8px;
}
.report-chat-form textarea {
  width: 100%;
  box-sizing: border-box;
  font: inherit;
}
.report-chat-question {
  font-weight: 700;
}
.report-chat-answer {
  white-space: pre-wrap;
  padding: 12px;
  border-radius: 12px;
  background: var(--soft-lime);
}
</style>
