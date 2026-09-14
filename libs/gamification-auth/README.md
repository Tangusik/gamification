# gamification-auth

Проверка access-токенов платформы геймификации. Общая для всех сервисов, потому что
формат токена и правила его проверки не имеют права разъехаться между ними.

Библиотека умеренно мала намеренно. В ней нет и не должно быть: доменной логики,
обращений к БД, знания про HTTP и FastAPI, выпуска токенов. Выпускает токены только
сервис `users` — остальные проверяют их локально по публичному ключу, не обращаясь к
`users` на каждый запрос.

## Использование

```python
from gamification_auth import decode_access_token, TokenError, TokenExpiredError

try:
    claims = decode_access_token(
        token,
        public_key=settings.jwt_public_key,
        algorithms=[settings.jwt_algorithm],
        audience=["fastapi-users:auth"],
    )
except TokenExpiredError:
    ...  # клиенту: обнови пару токенов и повтори
except TokenError:
    ...  # клиенту: иди на логин
```

`claims` — `AccessTokenClaims`: `subject`, `expires_at`, `token_id` (`jti`), `role`,
`institution_id`, плюс `raw` с полной нагрузкой.

## Что проверяется

- подпись;
- `exp` — **обязателен**. PyJWT проверяет срок, только если claim присутствует, поэтому
  валидно подписанный токен без срока приняли бы бессрочно;
- `sub` — обязателен: без него не установить предъявителя;
- `aud` — расхождение аудитории не должно открывать наши эндпоинты;
- алгоритм из списка, переданного вызывающим. **Никогда из заголовка токена**: иначе
  атакующий подставляет `alg: HS256` и подписывает токен нашим же публичным ключом как
  HMAC-секретом (algorithm confusion).

## Установка в разработке

Пакета в PyPI нет, он ставится из репозитория:

```bash
pip install -e libs/gamification-auth
```

Сервис, который его использует, объявляет зависимость по имени `gamification-auth`,
поэтому библиотеку нужно ставить **до** установки сервиса. На этапе Docker образ сервиса
обязан копировать `libs/` внутрь контекста сборки.

## Проверки

Собственного окружения у библиотеки пока нет — тесты гоняются из venv сервиса `users`:

```bash
cd services/users
.venv/Scripts/python.exe -m pytest ../../libs/gamification-auth
.venv/Scripts/python.exe -m ruff check ../../libs/gamification-auth
```
