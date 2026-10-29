<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ConditionSelector from '../components/ConditionSelector.vue'
import {
  copyConditions,
  emptyConditions,
  profileErrors,
  profilePayload,
  type ProfileForm,
} from '../models/healthProfile'
import { errorMessage } from '../api/client'
import { healthProfileUnavailable, useHealthProfileGateway } from '../services/healthProfileGateway'

const router = useRouter()
const gateway = useHealthProfileGateway()
const form = reactive<ProfileForm>({
  birthYear: '',
  birthMonth: '',
  sex: '',
  conditions: emptyConditions(),
})
// 登入方式尚未定案，保留原有密碼介面；不納入健康資料 payload。
const password = ref('')
const attempted = ref(false)
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
watch(form, () => {
  saved.value = false
})
const errorSummary = ref<HTMLElement | null>(null)
const errors = computed(() => profileErrors(form))
const canSave = computed(
  () =>
    gateway.available &&
    loaded.value &&
    !loading.value &&
    !saving.value &&
    !Object.values(errors.value).some(Boolean),
)
const errorFields = [
  { key: 'birthYear', id: 'birth-year' },
  { key: 'birthMonth', id: 'birth-month' },
  { key: 'sex', id: 'profile-sex' },
  { key: 'conditions', id: 'profile-conditions' },
] as const

async function loadProfile() {
  if (!gateway.available || loading.value || saving.value) return
  loading.value = true
  loaded.value = false
  error.value = ''
  try {
    const profile = await gateway.loadProfile()
    Object.assign(form, {
      birthYear: String(profile.birth_year),
      birthMonth: String(profile.birth_month),
      sex: profile.sex,
      conditions: copyConditions(profile.conditions),
    })
    loaded.value = true
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    loading.value = false
  }
}
function handleCancel() {
  if (!saving.value) void router.push('/member-center')
}
async function handleSubmit() {
  if (saving.value || loading.value) return
  attempted.value = true
  saved.value = false
  error.value = ''
  if (Object.values(errors.value).some(Boolean)) {
    await nextTick()
    errorSummary.value?.focus()
    return
  }
  if (!gateway.available || !loaded.value) {
    error.value = gateway.available
      ? '尚未載入會員資料，請重新載入後再儲存。'
      : healthProfileUnavailable
    return
  }
  saving.value = true
  try {
    await gateway.saveProfile(profilePayload(form))
    saved.value = true
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    saving.value = false
  }
}
onMounted(loadProfile)
</script>

<template>
  <main class="profile-settings">
    <h1>個人資料設定</h1>
    <p id="settings-notice">
      {{
        gateway.available
          ? '請確認基本資料與慢性疾病，完成後儲存變更。'
          : '目前無法載入或儲存會員資料，欄位預設空白，修改不會送出。儲存變更尚未開放。'
      }}
    </p>
    <p v-if="loading" role="status">正在載入會員資料…</p>
    <form novalidate aria-describedby="settings-notice" @submit.prevent="handleSubmit">
      <div
        v-if="attempted && Object.values(errors).some(Boolean)"
        ref="errorSummary"
        role="alert"
        tabindex="-1"
      >
        <p>請確認以下欄位：</p>
        <ul>
          <template v-for="field in errorFields" :key="field.key"
            ><li v-if="errors[field.key]">
              <a :href="`#${field.id}`">{{ errors[field.key] }}</a>
            </li></template
          >
        </ul>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="saved" role="status">個人資料已儲存。</p>
      <button v-if="gateway.available && !loaded && !loading" type="button" @click="loadProfile">
        重新載入會員資料
      </button>
      <fieldset :disabled="loading || saving">
        <legend>基本資料</legend>
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
          id="profile-conditions"
          v-model="form.conditions"
          :error="attempted ? errors.conditions : ''"
        />
      </fieldset>
      <section aria-labelledby="password-setting-title">
        <h2 id="password-setting-title">密碼設定</h2>
        <p id="password-setting-notice">密碼變更尚未開放。此欄位不會隨健康資料送出。</p>
        <label for="settings-password">密碼</label>
        <input
          id="settings-password"
          v-model="password"
          type="password"
          autocomplete="new-password"
          aria-describedby="password-setting-notice"
        />
      </section>
      <div class="profile-actions">
        <button type="button" :disabled="saving" @click="handleCancel">取消</button>
        <button class="primary-action" type="submit" :disabled="!canSave">
          {{ saving ? '儲存中…' : '儲存變更' }}
        </button>
      </div>
    </form>
  </main>
</template>

<style scoped>
.profile-settings {
  font-size: 18px;
  line-height: 1.65;
}
.profile-settings form {
  display: block;
}
.birth-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: 20px;
  margin-bottom: 24px;
}
.profile-settings button,
.profile-settings label:has(input[type='radio']) {
  min-height: 50px;
  font: inherit;
}
.profile-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}
.profile-actions button + button {
  margin-left: 0;
}
</style>
