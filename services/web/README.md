# services/web

Веб-фронтенд: Vite + React + TypeScript.

Рабочий режим разработки — контейнер: браузер ходит в nginx на
`http://127.0.0.1:8080`, оттуда же проксируется API. `npm run dev` оставлен
рабочим (прокси в `vite.config.ts`), но основным режимом не является.

- `npm install` — зависимости.
- `npm run build` — сборка в `dist`, эту статику отдаёт образ из
  `/usr/share/nginx/html`.
- `npm run lint` — oxlint.

База API — относительный `/api/v1`, задана константой в `src/api/client.ts`;
переменной окружения нет намеренно (CORS на бэкенде не подключён, домен один).
Токен хранится в `src/auth/tokenStorage.ts` и больше нигде.
