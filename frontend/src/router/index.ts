import { createRouter, createWebHistory } from 'vue-router'
import { useSessionStore } from '@/stores/session'
import { resolveAuthRedirect } from './authGuard'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash }
    return { top: 0, left: 0 }
  },
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/register',
      redirect: '/login',
    },
    {
      path: '/member-center',
      name: 'member-center',
      component: () => import('@/views/MemberCenterView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
    },
    {
      path: '/health-profile',
      name: 'health-profile',
      component: () => import('@/views/HealthProfileView.vue'),
    },
    {
      path: '/medicine-upload',
      name: 'medicine-upload',
      component: () => import('@/views/MedicineUploadView.vue'),
    },
    {
      path: '/medicine-review',
      name: 'medicine-review',
      component: () => import('@/views/MedicineReviewView.vue'),
    },
    {
      path: '/supplement-upload',
      name: 'supplement-upload',
      component: () => import('@/views/SupplementUploadView.vue'),
    },
    {
      path: '/supplement-review',
      name: 'supplement-review',
      component: () => import('@/views/SupplementReviewView.vue'),
    },
    { path: '/report/:caseId', name: 'report', component: () => import('@/views/ReportView.vue') },
    { path: '/reports', name: 'reports', component: () => import('@/views/ReportHistoryView.vue') },
    {
      path: '/reports/:reportId',
      name: 'report-detail',
      component: () => import('@/views/ReportView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  try {
    await session.load()
  } catch {
    // 查不到登入狀態（後端離線）時當作未登入，頁面本身會顯示錯誤。
  }
  return resolveAuthRedirect(to, session.me) ?? true
})

export default router
