import { createRouter, createWebHistory } from 'vue-router'
import { reviewDemoEnabled } from '../demo/enabled'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    ...(reviewDemoEnabled
      ? [
          {
            path: '/review-demo',
            name: 'review-demo',
            component: () => import('../demo/ReviewDemoView.vue'),
          },
        ]
      : [{ path: '/review-demo', redirect: '/' }]),
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
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
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
      path: '/api-test',
      name: 'api-test',
      component: () => import('@/views/ApiTestView.vue'),
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

export default router
