import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { healthProfileGatewayKey } from './services/healthProfileGateway'
import { healthProfileApi } from './services/healthProfileApi'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.provide(healthProfileGatewayKey, healthProfileApi)

app.mount('#app')
