<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import ConditionSelector from '../components/ConditionSelector.vue'
import {
  emptyConditions,
  profileErrors,
  profilePayload,
  type ProfileForm,
} from '../models/healthProfile'
import { errorMessage } from '../api/client'
import { healthProfileUnavailable, useHealthProfileGateway } from '../services/healthProfileGateway'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const session = useSessionStore()
const gateway = useHealthProfileGateway()
const form = reactive<ProfileForm>({
  birthYear: '',
  birthMonth: '',
  sex: '',
  conditions: emptyConditions(),
})
const attempted = ref(false)
const saving = ref(false)
const error = ref('')
const errorSummary = ref<HTMLElement | null>(null)
const errors = computed(() => profileErrors(form))
const canSave = computed(() => gateway.available && !saving.value)
const errorFields = [
  { key: 'birthYear', id: 'birth-year' },
  { key: 'birthMonth', id: 'birth-month' },
  { key: 'sex', id: 'profile-sex' },
  { key: 'conditions', id: 'initial-conditions' },
] as const

async function handleSubmit() {
  if (saving.value) return
  attempted.value = true
  error.value = ''
  if (Object.values(errors.value).some(Boolean)) {
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
    await gateway.saveProfile(profilePayload(form))
    session.markProfileCompleted()
    await router.push({ path: '/medicine-upload', query: { profileSaved: '1' } })
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="health-profile">
    <h1>完成基本資料</h1>
    <p>第一次使用，請先完成基本健康資料，儲存後即可上傳處方箋照片。</p>
    <p v-if="!gateway.available" id="health-profile-notice" role="status">
      {{ healthProfileUnavailable }}完成串接前，無法由此頁開始辨識。
    </p>
    <form
      novalidate
      :aria-describedby="!gateway.available ? 'health-profile-notice' : undefined"
      @submit.prevent="handleSubmit"
    >
      <div
        v-if="attempted && Object.values(errors).some(Boolean)"
        ref="errorSummary"
        role="alert"
        tabindex="-1"
      >
        <p>請先完成以下項目：</p>
        <ul>
          <template v-for="field in errorFields" :key="field.key"
            ><li v-if="errors[field.key]">
              <a :href="`#${field.id}`">{{ errors[field.key] }}</a>
            </li></template
          >
        </ul>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <fieldset :disabled="saving">
        <legend>基本健康資料</legend>
        <div class="birth-fields">
          <div>
            <label for="birth-year">出生年（西元）</label>
            <input
              id="birth-year"
              v-model="form.birthYear"
              type="text"
              inputmode="numeric"
              maxlength="4"
              required
              :aria-invalid="attempted && errors.birthYear ? 'true' : undefined"
              :aria-describedby="attempted && errors.birthYear ? 'birth-year-error' : undefined"
            />
            <p v-if="attempted && errors.birthYear" id="birth-year-error" role="alert">
              {{ errors.birthYear }}
            </p>
          </div>
          <div>
            <label for="birth-month">出生月</label>
            <input
              id="birth-month"
              v-model="form.birthMonth"
              type="text"
              inputmode="numeric"
              maxlength="2"
              required
              :aria-invalid="attempted && errors.birthMonth ? 'true' : undefined"
              :aria-describedby="attempted && errors.birthMonth ? 'birth-month-error' : undefined"
            />
            <p v-if="attempted && errors.birthMonth" id="birth-month-error" role="alert">
              {{ errors.birthMonth }}
            </p>
          </div>
        </div>
        <fieldset
          id="profile-sex"
          tabindex="-1"
          :aria-describedby="attempted && errors.sex ? 'profile-sex-error' : undefined"
          :aria-invalid="attempted && errors.sex ? 'true' : undefined"
        >
          <legend>性別（必選一項）</legend>
          <label
            ><input
              type="radio"
              name="profile-sex"
              value="male"
              :checked="form.sex === 'male'"
              @change="form.sex = 'male'"
            />男</label
          >
          <label
            ><input
              type="radio"
              name="profile-sex"
              value="female"
              :checked="form.sex === 'female'"
              @change="form.sex = 'female'"
            />女</label
          >
          <p v-if="attempted && errors.sex" id="profile-sex-error" role="alert">{{ errors.sex }}</p>
        </fieldset>
        <ConditionSelector
          id="initial-conditions"
          v-model="form.conditions"
          :error="attempted ? errors.conditions : ''"
        />
      </fieldset>
      <button class="primary-action" type="submit" :disabled="!canSave">
        {{ saving ? '儲存中…' : '儲存並開始上傳' }}
      </button>
      <p v-if="!gateway.available">儲存並開始上傳：尚未開放。</p>
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
.birth-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: 20px;
  margin-bottom: 24px;
}
.health-profile label:has(input[type='radio']) {
  min-height: 50px;
  font: inherit;
}
</style>
