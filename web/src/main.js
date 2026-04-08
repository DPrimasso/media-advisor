import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue]', info, err)
}
app.use(router)
app.mount('#app')
