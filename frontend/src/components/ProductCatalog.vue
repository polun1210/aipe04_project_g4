<!-- API 串接練習，尚未接入正式頁面，待團隊整合 -->

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getCatalog, type CatalogResponse } from '@/api/catalog'

const catalog = ref<CatalogResponse>()
const loading = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  loading.value = true

  try {
    catalog.value = await getCatalog()
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '目錄載入失敗'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <p v-if="loading">載入中……</p>
  <p v-else-if="errorMessage">{{ errorMessage }}</p>

  <label
    v-for="condition in catalog?.known_conditions"
    :key="condition.condition_code"
  >
    <input
      type="checkbox"
      :value="condition.condition_code"
    >
    {{ condition.display_name_zh }}
  </label>
</template>