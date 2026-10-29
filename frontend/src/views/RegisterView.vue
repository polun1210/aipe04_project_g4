<script setup lang="ts">
import { reactive } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

type Sex = '' | 'male' | 'female'
type ConditionCode =
  | 'hypertension'
  | 't2dm'
  | 'dyslipidemia'
  | 'chronic_arthritis'
  | 'chronic_insomnia'

interface RegisterForm {
  birthYear: string
  birthMonth: string
  sex: Sex
  email: string
  password: string
  conditions: {
    selected: ConditionCode[]
    none_selected: boolean
  }
}

const router = useRouter()
const form = reactive<RegisterForm>({
  birthYear: '',
  birthMonth: '',
  sex: '',
  email: '',
  password: '',
  conditions: {
    selected: [],
    none_selected: false,
  },
})

const conditionOptions: { code: ConditionCode; label: string }[] = [
  { code: 'hypertension', label: '高血壓' },
  { code: 't2dm', label: '第二型糖尿病' },
  { code: 'dyslipidemia', label: '高血脂' },
  { code: 'chronic_arthritis', label: '慢性關節炎／長期關節疼痛' },
  { code: 'chronic_insomnia', label: '慢性失眠' },
]

function handleConditionChange(): void {
  if (form.conditions.selected.length > 0) {
    form.conditions.none_selected = false
  }
}

function handleNoneChange(): void {
  if (form.conditions.none_selected) {
    form.conditions.selected = []
  }
}

function handleCancel(): void {
  void router.push('/')
}

function handleSubmit(): void {
  // 尚無註冊 API，暫不執行註冊、儲存或傳送表單。
  return
}
</script>

<template>
  <header>
    <RouterLink to="/">補對了嗎?</RouterLink>
  </header>

  <main>
    <h1>註冊</h1>
    <p id="register-notice">目前僅提供註冊表單，註冊功能尚未開放，資料不會送出。</p>

    <form aria-describedby="register-notice" @submit.prevent="handleSubmit">
      <p>
        <label for="birth-year">出生年（YYYY）</label>
        <input
          id="birth-year"
          v-model="form.birthYear"
          type="text"
          inputmode="numeric"
          maxlength="4"
          pattern="[0-9]{4}"
          required
        />
      </p>

      <p>
        <label for="birth-month">出生月（MM）</label>
        <input
          id="birth-month"
          v-model="form.birthMonth"
          type="text"
          inputmode="numeric"
          maxlength="2"
          pattern="0[1-9]|1[0-2]"
          required
        />
      </p>

      <fieldset>
        <legend>性別</legend>
        <label>
          <input v-model="form.sex" type="radio" name="sex" value="male" />
          男
        </label>
        <label>
          <input v-model="form.sex" type="radio" name="sex" value="female" />
          女
        </label>
      </fieldset>

      <p>
        <label for="register-email">帳號（Email）</label>
        <input id="register-email" v-model="form.email" type="email" autocomplete="username" />
      </p>

      <p>
        <label for="register-password">密碼</label>
        <input
          id="register-password"
          v-model="form.password"
          type="password"
          autocomplete="new-password"
        />
      </p>

      <fieldset>
        <legend>慢性疾病（可複選）</legend>
        <p v-for="condition in conditionOptions" :key="condition.code">
          <label>
            <input
              v-model="form.conditions.selected"
              type="checkbox"
              :value="condition.code"
              @change="handleConditionChange"
            />
            {{ condition.label }}
          </label>
        </p>
        <p>
          <label>
            <input
              v-model="form.conditions.none_selected"
              type="checkbox"
              @change="handleNoneChange"
            />
            以上皆無
          </label>
        </p>
      </fieldset>

      <button type="button" @click="handleCancel">取消</button>
      <button type="submit" disabled>確認（尚未開放）</button>
    </form>
  </main>
</template>
