# Образ веб-фронтенда: сборка статики + nginx, который её отдаёт и
# заодно играет роль шлюза к API.
#
# Контекст сборки — services/web, а НЕ корень репозитория (в отличие от
# services/users/Dockerfile, которому корень нужен ради libs/):
# у фронта зависимостей вне своего каталога нет.
#
#   docker build -t gamification/web:dev services/web
#
# Из-за своего контекста здесь работает services/web/.dockerignore,
# а не корневой — см. комментарий в нём.

# ---------------------------------------------------------------- build
FROM node:22-alpine AS builder

WORKDIR /app

# Манифесты — отдельным слоем до исходников: они меняются реже кода,
# и слой с установкой зависимостей переиспользуется между сборками.
COPY package.json package-lock.json* ./

# npm ci, а не install: ставит ровно то, что записано в lock-файле.
# Фолбэк на install нужен только пока lock-файла может не быть.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

# Договор с оркестрацией: сборка кладёт статику в dist.
RUN npm run build

# -------------------------------------------------------------- runtime
FROM nginx:1.27-alpine AS runtime

# Дефолтный конфиг образа заменяется целиком: он отдаёт свою
# приветственную страницу и ничего не знает про SPA-fallback и про API.
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

# Сниппеты заголовков (add_header не наследуется в location со своим
# add_header — default.conf подключает их через include в нескольких
# location, см. комментарии там же).
COPY nginx/security-headers.conf /etc/nginx/security-headers.conf
COPY nginx/csp.conf              /etc/nginx/csp.conf
COPY nginx/csp-api.conf          /etc/nginx/csp-api.conf

RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# В nginx:1.27-alpine curl нет, wget есть. Проба бьёт в корень: он
# отдаёт index.html и не зависит от доступности сервиса users —
# нездоровый бэкенд не должен ронять раздачу статики.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget --quiet --spider http://127.0.0.1:80/ || exit 1
