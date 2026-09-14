import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Рабочий режим разработки — контейнер: браузер ходит в nginx на 127.0.0.1:8080.
// Прокси ниже нужен, только если запускать `npm run dev` на хосте. Правила
// обязаны повторять маппинг nginx/default.conf по префиксам (users и
// gamification — разные сервисы, разные порты на хосте из
// docker-compose.dev.yml): снимается лишь версия `/api/v1`, путь
// `/users/...` или `/institutions/...` остаётся. Иначе dev и прод
// разъедутся, и это вскроется только на проде.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/v1/users': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1/, ''),
      },
      '/api/v1/institutions': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/v1/, ''),
      },
    },
  },
})
