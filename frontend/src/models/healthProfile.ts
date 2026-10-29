// 對應 app/schemas/case.py 的 AccountProfile 與 enums.py 的封閉代碼。
export type Sex = 'male' | 'female'
export type ConditionCode =
  'hypertension' | 't2dm' | 'dyslipidemia' | 'chronic_arthritis' | 'chronic_insomnia'

export interface ConditionSelection {
  selected: ConditionCode[]
  none_selected: boolean
}

export const conditionOptions: { code: ConditionCode; label: string }[] = [
  { code: 'hypertension', label: '高血壓' },
  { code: 't2dm', label: '第二型糖尿病' },
  { code: 'dyslipidemia', label: '高血脂' },
  { code: 'chronic_arthritis', label: '慢性關節炎／長期關節疼痛' },
  { code: 'chronic_insomnia', label: '慢性失眠' },
]

export const emptyConditions = (): ConditionSelection => ({ selected: [], none_selected: false })
export const copyConditions = (value: ConditionSelection): ConditionSelection => ({
  selected: [...value.selected],
  none_selected: value.none_selected,
})

export function changeCondition(
  value: ConditionSelection,
  code: ConditionCode,
  checked: boolean,
): ConditionSelection {
  return {
    selected: checked
      ? [...new Set([...value.selected, code])]
      : value.selected.filter((item) => item !== code),
    none_selected: checked ? false : value.none_selected,
  }
}

export function changeNone(value: ConditionSelection, checked: boolean): ConditionSelection {
  return { selected: checked ? [] : [...value.selected], none_selected: checked }
}

export function conditionsError(value: ConditionSelection): string {
  if (value.selected.some((code) => !conditionOptions.some((item) => item.code === code)))
    return '慢性疾病選項無法辨識，請重新選擇。'
  if (value.none_selected && value.selected.length)
    return '「以上皆無」不能與其他慢性疾病同時選擇。'
  return value.none_selected || value.selected.length ? '' : '請選擇慢性疾病，或勾選「以上皆無」。'
}

export interface AccountProfile {
  birth_year: number
  birth_month: number
  sex: Sex
  conditions: ConditionSelection
}

export interface ProfileForm {
  birthYear: string
  birthMonth: string
  sex: Sex | ''
  conditions: ConditionSelection
}

export function profileErrors(form: ProfileForm) {
  return {
    birthYear:
      /^\d{4}$/.test(form.birthYear) &&
      Number(form.birthYear) >= 1900 &&
      Number(form.birthYear) <= 2100
        ? ''
        : '請填寫 1900 至 2100 之間的四位數出生年。',
    birthMonth:
      /^\d{1,2}$/.test(form.birthMonth) &&
      Number(form.birthMonth) >= 1 &&
      Number(form.birthMonth) <= 12
        ? ''
        : '請填寫 1 至 12 之間的出生月。',
    sex: form.sex === 'male' || form.sex === 'female' ? '' : '請選擇性別（男或女）。',
    conditions: conditionsError(form.conditions),
  }
}

export function profilePayload(form: ProfileForm): AccountProfile {
  if (Object.values(profileErrors(form)).some(Boolean)) throw new Error('個人資料尚未填寫完整。')
  return {
    birth_year: Number(form.birthYear),
    birth_month: Number(form.birthMonth),
    sex: form.sex as Sex,
    conditions: copyConditions(form.conditions),
  }
}
