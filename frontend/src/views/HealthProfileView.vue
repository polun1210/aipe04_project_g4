<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import ConditionSelector from '../components/ConditionSelector.vue'
import { conditionsError, copyConditions, emptyConditions } from '../models/healthProfile'
import { errorMessage } from '../api/client'
import { healthProfileUnavailable, useHealthProfileGateway } from '../services/healthProfileGateway'

const router = useRouter()
const gateway = useHealthProfileGateway()
const conditions = ref(emptyConditions())
const attempted = ref(false)
const saving = ref(false)
const error = ref('')
const errorSummary = ref<HTMLElement | null>(null)
const selectionError = computed(() => conditionsError(conditions.value))
const canSave = computed(() => gateway.available && !saving.value && !selectionError.value)

async function handleSubmit() {
  if (saving.value) return
  attempted.value = true
  error.value = ''
  if (selectionError.value) {
    await nextTick()
    errorSummary.value?.focus()
    return
  }
  if (!gateway.available) {
    error.value = healthProfileUnavailable
    return
  }
  saving.value = true
  try {
    await gateway.saveInitialConditions(copyConditions(conditions.value))
    await router.push('/medicine-upload')
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="health-profile">
    <h1>歡迎使用補藥亂吃！</h1>
    <p>開始使用前，請先完成基本健康資料。</p>
    <p v-if="!gateway.available" id="health-profile-notice" role="status">
      {{ healthProfileUnavailable }}完成串接前，無法由此頁開始辨識。
    </p>
    <form
      novalidate
      :aria-describedby="!gateway.available ? 'health-profile-notice' : undefined"
      @submit.prevent="handleSubmit"
    >
      <div v-if="attempted && selectionError" ref="errorSummary" role="alert" tabindex="-1">
        <p>請先完成以下項目：</p>
        <a href="#initial-conditions">{{ selectionError }}</a>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <fieldset :disabled="saving">
        <legend>基本健康資料</legend>
        <ConditionSelector
          id="initial-conditions"
          v-model="conditions"
          :error="attempted ? selectionError : ''"
        />
      </fieldset>
      <button class="primary-action" type="submit" :disabled="!canSave">
        {{ saving ? '儲存中…' : '儲存並開始使用' }}
      </button>
      <p v-if="!gateway.available">儲存並開始使用：尚未開放。</p>
    </form>
  </main>
</template>

<style scoped>
.health-profile {
  font-size: 18px;
  line-height: 1.65;
}
.health-profile button {
  min-height: 50px;
  font: inherit;
}
</style>
