<script setup lang="ts">
import { reactive } from 'vue'
import { useRouter } from 'vue-router'

interface SettingsForm {
  birthYear: string
  birthMonth: string
  password: string
}

const router = useRouter()
const form = reactive<SettingsForm>({
  birthYear: '',
  birthMonth: '',
  password: '',
})

function handleCancel(): void {
  void router.push('/member-center')
}

function handleSubmit(): void {
  // 尚無會員資料 API，暫不儲存或傳送表單。
  return
}
</script>

<template>
  <main>
    <h1>設定</h1>
    <p id="settings-notice">目前無法載入或儲存會員資料，欄位預設空白，修改不會送出。</p>

    <form aria-describedby="settings-notice" @submit.prevent="handleSubmit">
      <p>
        <label for="birth-year">出生年（YYYY）</label>
        <input
          id="birth-year"
          v-model="form.birthYear"
          type="text"
          inputmode="numeric"
          maxlength="4"
          pattern="[0-9]{4}"
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
        />
      </p>

      <p>
        <label for="settings-password">密碼</label>
        <input
          id="settings-password"
          v-model="form.password"
          type="password"
          autocomplete="new-password"
        />
      </p>

      <button type="button" @click="handleCancel">取消</button>
      <button type="submit" disabled>確認（尚未開放）</button>
    </form>
  </main>
</template>
