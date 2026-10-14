import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
    },
    {
      path: '/api-test',
      name: 'api-test',
      component: () => import('@/views/ApiTestView.vue'),
    },
  ],
})

export default router
