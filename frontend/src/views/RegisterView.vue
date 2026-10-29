<script setup lang="ts">
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import ConditionSelector from '../components/ConditionSelector.vue'
import { type Sex as ProfileSex, type ConditionSelection } from '../models/healthProfile'

type Sex = '' | ProfileSex

interface RegisterForm {
  birthYear: string
  birthMonth: string
  sex: Sex
  email: string
  password: string
  conditions: ConditionSelection
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

function handleCancel(): void {
  void router.push('/')
}

function handleSubmit(): void {
  // 尚無註冊 API，暫不執行註冊、儲存或傳送表單。
  return
}
</script>

<template>
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

      <ConditionSelector
        id="register-conditions"
        v-model="form.conditions"
        legend="慢性疾病（可複選）"
      />

      <button type="button" @click="handleCancel">取消</button>
      <button type="submit" disabled>確認（尚未開放）</button>
    </form>
  </main>
</template>

<style scoped>
button {
  min-height: 50px;
}
</style>
