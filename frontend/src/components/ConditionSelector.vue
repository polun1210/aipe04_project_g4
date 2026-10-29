<script setup lang="ts">
import {
  changeCondition,
  changeNone,
  conditionOptions,
  type ConditionSelection,
} from '../models/healthProfile'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: ConditionSelection
    legend?: string
    error?: string
  }>(),
  { legend: '是否有慢性疾病？', error: '' },
)
const emit = defineEmits<{ 'update:modelValue': [value: ConditionSelection] }>()
</script>

<template>
  <fieldset
    :id="id"
    class="condition-selector"
    tabindex="-1"
    :aria-invalid="error ? 'true' : undefined"
    :aria-describedby="`${id}-hint${error ? ` ${id}-error` : ''}`"
  >
    <legend>{{ legend }}</legend>
    <p :id="`${id}-hint`">可複選；若沒有以下疾病，請勾選「以上皆無」。</p>
    <div class="condition-options">
      <label v-for="condition in conditionOptions" :key="condition.code" class="condition-option">
        <input
          type="checkbox"
          :value="condition.code"
          :checked="modelValue.selected.includes(condition.code)"
          @change="
            emit(
              'update:modelValue',
              changeCondition(
                props.modelValue,
                condition.code,
                ($event.target as HTMLInputElement).checked,
              ),
            )
          "
        />
        {{ condition.label }}
      </label>
      <label class="condition-option">
        <input
          type="checkbox"
          value="none"
          :checked="modelValue.none_selected"
          @change="
            emit(
              'update:modelValue',
              changeNone(props.modelValue, ($event.target as HTMLInputElement).checked),
            )
          "
        />
        以上皆無
      </label>
    </div>
    <p v-if="error" :id="`${id}-error`" role="alert">{{ error }}</p>
  </fieldset>
</template>

<style scoped>
.condition-selector {
  font-size: 18px;
}
.condition-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 12px;
}
.condition-selector .condition-option {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 50px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line, #dce2e4);
  border-radius: 12px;
  cursor: pointer;
}
.condition-selector .condition-option:has(input:checked) {
  background: var(--soft-lime, #f0f5e3);
  border-color: var(--navy, #142332);
}
.condition-selector input {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}
.condition-selector [role='alert'] {
  margin-top: 16px;
}
</style>
