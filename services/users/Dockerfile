# Образ сервиса users.
#
# Контекст сборки — КОРЕНЬ репозитория, не services/users:
# зависимость gamification-auth в PyPI отсутствует и ставится из
# libs/gamification-auth ДО установки сервиса, иначе pip не разрешит её
# по имени и сборка упадёт.
#
#   docker build -f services/users/Dockerfile -t users:local .

# ---------------------------------------------------------------- build
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Venv, а не системный python: в финальный образ уезжает один каталог
# без следов сборки.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Общая библиотека — первой и отдельным слоем: она меняется реже кода
# сервиса, поэтому её слой переиспользуется между сборками.
COPY libs/gamification-auth /src/libs/gamification-auth
RUN pip install /src/libs/gamification-auth

# Сервис ставится колесом (hatchling), поэтому нужен весь пакет app/.
COPY services/users /src/services/users
RUN pip install /src/services/users

# -------------------------------------------------------------- runtime
FROM python:3.13-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    # Логи идут в stdout немедленно, без буфера: иначе docker logs и
    # сборщик логов в k8s видят их пачками и с задержкой.
    PYTHONUNBUFFERED=1

# Непривилегированный пользователь: процесс в контейнере не должен быть
# root даже при отсутствии смонтированных томов.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# Исходники нужны в образе и после установки колеса: alembic.ini и
# alembic/ лежат рядом с пакетом и запускаются шагом миграций.
COPY --chown=app:app services/users /app

USER app

EXPOSE 8000

# В python:3.13-slim нет ни curl, ни wget — проба пишется на stdlib.
# С неработающей пробой контейнер навсегда останется unhealthy, а
# зависящие от него сервисы не стартуют.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

# --factory обязателен: модульного объекта app нет намеренно.
# --workers 1 — масштабирование горизонтальное, репликами.
# --proxy-headers --forwarded-allow-ips="*" (П10): без них uvicorn
# видит IP и схему контейнера nginx/Caddy вместо клиента — в логах IP
# прокси, request.url.scheme=http даже за HTTPS. "*" допустим: порт
# сервиса наружу не публикуется (docker-compose.yml), довериться можно
# любому, кто способен достучаться до users:8000 внутри сети compose.
CMD ["uvicorn", "app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
