<script setup lang="ts">
import { createApp, onBeforeUnmount, onMounted, ref } from 'vue'
import { createPinia, disposePinia, getActivePinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, useRouter } from 'vue-router'
import DemoShell from './DemoShell.vue'
import DemoReportView from './DemoReportView.vue'
import { reviewDemoKey } from './context'
import { reviewDemoEnabled } from './enabled'
import MedicineReviewView from '../views/MedicineReviewView.vue'
import SupplementReviewView from '../views/SupplementReviewView.vue'
import { useMedicineFlowStore } from '../stores/medicineFlow'
import { useSupplementFlowStore } from '../stores/supplementFlow'
import type { DrugDraft } from '../api/drugs'
import type { SupplementDraft } from '../api/supplements'
import drugExample from '../../../docs/schemas/examples/04_drug_draft.json'
import supplementExample from '../../../docs/schemas/examples/04_supplement_draft.json'

const host = ref<HTMLElement | null>(null)
const outerRouter = useRouter()
const parentPinia = getActivePinia()
let demoApp: ReturnType<typeof createApp> | undefined
let demoPinia: ReturnType<typeof createPinia> | undefined
let mounted = false
onMounted(async () => {
  if (!reviewDemoEnabled || !host.value) return
  // Separate application + Pinia + memory history: demo rows and exceptions
  // cannot leak into the regular stores, report routes or browser history.
  demoPinia = createPinia()
  const medicine = useMedicineFlowStore(demoPinia)
  const supplement = useSupplementFlowStore(demoPinia)
  const drug = structuredClone(drugExample) as DrugDraft
  const product = structuredClone({
    ...supplementExample,
    nutrients: supplementExample.nutrients.map((row) => ({
      ...row,
      nutrient_form_code: row.nutrient_form_code ?? null,
      per_serving: row.per_serving ?? null,
      unit: row.unit ?? null,
      stated_elemental_amount: row.stated_elemental_amount ?? null,
      requires_user_input: row.requires_user_input ?? false,
    })),
  }) as SupplementDraft
  drug.extraction_meta.ocr_version = 'stub-review-demo'
  product.extraction_meta.ocr_version = 'stub-review-demo'
  medicine.addDrugBatch([], drug)
  supplement.addBatch([], product)
  const demoRouter = createRouter({
    history: createMemoryHistory(),
    scrollBehavior: () => ({ top: 0 }),
    routes: [
      { path: '/', redirect: '/medicine-review' },
      { path: '/medicine-review', component: MedicineReviewView },
      { path: '/supplement-review', component: SupplementReviewView },
      { path: '/demo-report', component: DemoReportView },
      { path: '/:pathMatch(.*)*', component: { render: () => null } },
    ],
  })
  let reportAllowed = false
  demoRouter.beforeEach((to) => {
    if (to.path === '/demo-report') return reportAllowed ? true : '/medicine-review'
    if (['/medicine-review', '/supplement-review'].includes(to.path)) return true
    void outerRouter.push(to.fullPath)
    return false
  })
  demoApp = createApp(DemoShell, {
    exit: () => {
      void outerRouter.push('/')
    },
  })
  demoApp
    .use(demoPinia)
    .use(demoRouter)
    .provide(reviewDemoKey, {
      async finish() {
        reportAllowed = true
        return demoRouter.push('/demo-report')
      },
    })
  await demoRouter.push('/medicine-review')
  // The host may have been removed while the asynchronous route initialized.
  if (host.value) {
    demoApp.mount(host.value)
    mounted = true
  }
  setActivePinia(parentPinia)
})
onBeforeUnmount(() => {
  if (mounted) demoApp?.unmount()
  if (demoPinia) {
    useMedicineFlowStore(demoPinia).resetFlow()
    useSupplementFlowStore(demoPinia).resetFlow()
    disposePinia(demoPinia)
  }
  setActivePinia(parentPinia)
})
</script>

<template><div ref="host" data-review-demo-host /></template>
