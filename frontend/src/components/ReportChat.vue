<script setup lang="ts">
import { ref } from 'vue'
import { askReport } from '../api/reports'
import { ApiError } from '../api/client'

const props = defineProps<{ reportId: string }>()
const presets = ['哪些項目超過上限？', '哪些項目需要問醫師或藥師？']
const asked = ref('')
const answer = ref('')
const error = ref('')
const busy = ref(false)
let request = 0

async function ask(question: string) {
  const current = ++request
  asked.value = question
  answer.value = ''
  error.value = ''
  busy.value = true
  try {
    const result = await askReport(props.reportId, question)
    if (current === request) answer.value = result.answer
  } catch (reason) {
    if (current === request)
      error.value =
        reason instanceof ApiError && reason.body.error.code === 'chat_disabled'
          ? '對話功能未啟用'
          : '目前無法回答'
  } finally {
    if (current === request) busy.value = false
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
    <p v-if="busy" role="status">正在回答…</p>
    <template v-if="answer">
      <p class="report-chat-question">{{ asked }}</p>
      <p class="report-chat-answer">{{ answer }}</p>
    </template>
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
