# Деплой на VPS: пошаговая инструкция

Выполняется человеком по порядку, сверху вниз. На каждом шаге указано, где выполнять команду: **[VPS]** —
в SSH-сессии на сервере, **[ПК]** — на своём компьютере. После команды указан ожидаемый результат. Если
результат другой, дальше не идти: раздел «Если что-то пошло не так» в конце.

Исходные данные: Ubuntu 24.04, 4 ГБ RAM, 40 ГБ диска, IP `77.232.135.105`, домен `your-gamification.ru`
(DNS уже указывает на сервер), репозиторий `github.com/Tangusik/gamification`. Решения, на которых
построена инструкция, — `.claude/answers/05-deploy.md`.

## 0. Перед началом — на своём компьютере

1. **[ПК]** Все изменения закоммичены и отправлены в GitHub (`git status` чист, `git push` выполнен).
   На сервер попадает только то, что лежит в GitHub.
2. Под рукой менеджер паролей: в него сохраняются секреты из шага 4.
3. Под рукой почта для уведомлений Let's Encrypt и почта с паролем для первого администратора.

## 1. Сервер: система и безопасность

1. **[ПК]** Зайти на сервер под root: `ssh root@77.232.135.105`.
2. **[VPS]** Проверить ОС и обновить систему:
   ```sh
   lsb_release -a            # ожидается Ubuntu 24.04
   apt update && apt upgrade -y
   timedatectl               # ожидается "System clock synchronized: yes"
   ```
   Если синхронизации нет: `timedatectl set-ntp true`. Без точного времени не выпустится сертификат и
   сломаются токены.
3. **[VPS]** Завести рабочего пользователя (далее `deploy`):
   ```sh
   adduser deploy
   usermod -aG sudo deploy
   mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/
   chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
   ```
   Если у root нет `~/.ssh/authorized_keys` (вход был по паролю): на ПК выполнить
   `ssh-keygen -t ed25519` (если ключа ещё нет), затем вставить содержимое `~/.ssh/id_ed25519.pub`
   в `/home/deploy/.ssh/authorized_keys` на сервере.
4. **[ПК]** В **новом** окне проверить вход по ключу: `ssh deploy@77.232.135.105`. Пароль спрашиваться
   не должен. Первое окно не закрывать, пока проверка не прошла.
5. **[VPS]** Запретить вход по паролю и под root:
   ```sh
   printf 'PasswordAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/00-hardening.conf
   sudo sshd -t && sudo systemctl restart ssh
   ```
   `sshd -t` не должен ничего вывести. Ещё раз проверить вход `ssh deploy@…` из нового окна.
   Дальше все команды — под `deploy`.
6. **[VPS]** Файрвол:
   ```sh
   sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
   sudo ufw enable
   sudo ufw status           # ожидаются 22, 80, 443/tcp, 443/udp — ALLOW
   ```
   Если в панели хостинга есть свой файрвол — открыть там те же порты.
7. **[VPS]** Swap 2 ГБ — страховка от нехватки памяти при сборке образов:
   ```sh
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
   sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   free -h                   # в строке Swap ожидается 2.0Gi
   ```

## 2. Docker

1. **[VPS]** Установить Docker Engine и Compose из официального репозитория:
   ```sh
   sudo apt-get install -y ca-certificates curl git
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
     | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo usermod -aG docker deploy
   ```
2. Выйти из SSH и зайти снова, чтобы группа `docker` применилась.
3. **[VPS]** Проверить:
   ```sh
   docker compose version    # ожидается "Docker Compose version v2..."
   docker run --rm hello-world
   ```

## 3. Код

1. **[VPS]** Создать ключ только для чтения репозитория:
   ```sh
   ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "gamification-vps"
   cat ~/.ssh/github_deploy.pub
   ```
2. В GitHub: репозиторий → **Settings → Deploy keys → Add deploy key**. Вставить выведенную строку,
   галочку **Allow write access не ставить**.
3. **[VPS]** Склонировать в `/opt/gamification`:
   ```sh
   printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   chmod 600 ~/.ssh/config
   sudo mkdir -p /opt/gamification && sudo chown deploy:deploy /opt/gamification
   git clone git@github.com:Tangusik/gamification.git /opt/gamification
   cd /opt/gamification && git log -1 --oneline   # последний коммит совпадает с тем, что на ПК
   ```

## 4. Секреты: файл `deploy/.env.production`

Все команды шага — **[VPS]**, в каталоге `/opt/gamification`.

1. Создать файл из образца:
   ```sh
   cd /opt/gamification
   cp deploy/.env.production.example deploy/.env.production
   chmod 600 deploy/.env.production
   ```
2. Сгенерировать пароли, служебные секреты и теги образов. Каждое значение случайное; все пять секретов
   получаются разными:
   ```sh
   F=deploy/.env.production
   set_var() { sed -i "s|^$1=.*|$1=$2|" "$F"; }
   set_var POSTGRES_PASSWORD             "$(openssl rand -hex 24)"
   set_var GAMIFICATION_DB_PASSWORD      "$(openssl rand -hex 24)"
   set_var GAMIFICATION_APP_DB_PASSWORD  "$(openssl rand -hex 24)"
   set_var INTERNAL_GAMIFICATION_SECRET  "$(openssl rand -hex 32)"
   set_var INTERNAL_USERS_SECRET         "$(openssl rand -hex 32)"
   TAG=$(git rev-parse --short HEAD)
   set_var USERS_IMAGE_TAG "$TAG"; set_var GAMIFICATION_IMAGE_TAG "$TAG"
   echo "WEB_IMAGE_TAG=$TAG" >> "$F"
   ```
3. Сгенерировать **новую** пару ключей подписи токенов и записать её в файл. Ключи из окружения
   разработки на проде использовать нельзя:
   ```sh
   umask 077
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out /tmp/jwt_private.pem
   openssl pkey -in /tmp/jwt_private.pem -pubout -out /tmp/jwt_public.pem
   sed -i '/^USERS_JWT_PRIVATE_KEY=/d;/^USERS_JWT_PUBLIC_KEY=/d' "$F"
   printf 'USERS_JWT_PRIVATE_KEY="%s"\n' "$(cat /tmp/jwt_private.pem)" >> "$F"
   printf 'USERS_JWT_PUBLIC_KEY="%s"\n'  "$(cat /tmp/jwt_public.pem)"  >> "$F"
   shred -u /tmp/jwt_private.pem /tmp/jwt_public.pem
   ```
4. Вписать почты и пароль администратора: `nano deploy/.env.production`, заполнить строки
   - `ACME_EMAIL=` — почта для уведомлений Let's Encrypt;
   - `USERS_BOOTSTRAP_ADMIN_EMAIL=` и `USERS_BOOTSTRAP_ADMIN_PASSWORD=` — первый администратор,
     пароль не короче 8 символов, только буквы и цифры.
5. Проверить, что пустых обязательных значений не осталось:
   ```sh
   grep -E '^(POSTGRES_PASSWORD|GAMIFICATION_DB_PASSWORD|GAMIFICATION_APP_DB_PASSWORD|INTERNAL_GAMIFICATION_SECRET|INTERNAL_USERS_SECRET|ACME_EMAIL|USERS_IMAGE_TAG)=$' "$F"
   grep -c 'BEGIN' "$F"      # ожидается 2
   ```
   Первая команда не должна ничего вывести.
6. **Сохранить копию файла в менеджер паролей** (`cat deploy/.env.production`, скопировать целиком).
   Без неё после потери сервера пропадут ключ подписи и пароли базы.

## 5. Первый запуск

Все команды compose — **только с `--env-file deploy/.env.production`**. Без него поднимется стек с
паролями и ключами разработки, и ни одна проверка об этом не предупредит. Чтобы не ошибиться, в каждой
новой SSH-сессии сначала задать сокращение:

```sh
cd /opt/gamification
C="docker compose --env-file deploy/.env.production -f docker-compose.yml"
```

1. **[VPS]** Порты 80 и 443 свободны: `sudo ss -ltnp | grep -E ':(80|443) '` ничего не выводит.
   Если что-то слушает (например, оставленный `python3 -m http.server`) — остановить.
2. **[VPS]** Проверить конфигурацию: `$C config --quiet` — ничего не выводит. Ошибка вида
   `... is required` называет незаполненную переменную — вернуться к шагу 4.
3. **[VPS]** Собрать образы (10–20 минут): `$C build`. Ожидается окончание без `ERROR`.
4. **[VPS]** Запустить: `$C up -d`.
5. **[VPS]** Через 1–2 минуты проверить состояние: `$C ps -a`. Ожидается:
   - `migrate` и `migrate-gamification` — `Exited (0)`;
   - `postgres`, `redis`, `users`, `gamification`, `web` — `Up … (healthy)`;
   - `caddy` — `Up`.

   Если миграция не `Exited (0)`: `$C logs migrate migrate-gamification`.
6. **[VPS]** Дождаться сертификата: `$C logs -f caddy`. Ждать строку `certificate obtained successfully`
   (обычно меньше минуты), затем Ctrl+C. **Не перезапускать Caddy в цикле**, если строки нет: у
   Let's Encrypt лимит на число выпусков. Сначала раздел «Если что-то пошло не так».

## 6. Проверка работы

1. **[ПК]** Проверки по HTTP (в PowerShell писать `curl.exe`, а не `curl`):
   ```sh
   curl -sI http://your-gamification.ru/                  # 308, Location: https://your-gamification.ru/
   curl -sI https://your-gamification.ru/                 # 200, есть strict-transport-security
   curl -s -o /dev/null -w "%{http_code}\n" https://your-gamification.ru/api/v1/users/me        # 401
   curl -s -o /dev/null -w "%{http_code}\n" https://your-gamification.ru/api/v1/openapi.json    # 404
   ```
2. **Браузер**, `https://your-gamification.ru`:
   1. Войти администратором из шага 4.4 и сменить пароль.
   2. Создать учреждение, выпустить приглашение.
   3. В другом браузере (или окне инкогнито) зарегистрироваться по ссылке-приглашению.
   4. Начислить второму пользователю валюту и купить привилегию.
   5. Оставить вкладку на 16 минут, затем обновить страницу — повторный вход не нужен.
3. **[VPS]** Реальный IP в логах: `$C logs users | tail -20` — в строках запросов IP вашего ПК, а не
   `172.x.x.x`.
4. **Телефон:** установить `app-release.apk` версии `1.0.0+2` (скопировать файл на телефон, разрешить
   установку из неизвестных источников). Войти, открыть учреждение и маркет. Если стоит сборка `+1`,
   новая встаёт поверх без удаления.
5. **[VPS]** Убрать пароль администратора из файла: очистить значения `USERS_BOOTSTRAP_ADMIN_EMAIL` и
   `USERS_BOOTSTRAP_ADMIN_PASSWORD` в `nano deploy/.env.production`, затем `$C up -d --no-deps users`.
   Проверить, что вход новым паролем работает.

Деплой завершён.

## 7. Обновление до новой версии

1. **[ПК]** Изменения закоммичены и отправлены в GitHub.
2. **[VPS]**
   ```sh
   cd /opt/gamification
   C="docker compose --env-file deploy/.env.production -f docker-compose.yml"
   df -h /                                   # свободно не меньше 5 ГБ
   grep _IMAGE_TAG deploy/.env.production    # записать текущий тег — он нужен для отката
   git pull
   TAG=$(git rev-parse --short HEAD)
   sed -i "s|^\(USERS\|GAMIFICATION\|WEB\)_IMAGE_TAG=.*|\1_IMAGE_TAG=$TAG|" deploy/.env.production
   $C build && $C up -d
   $C ps -a                                  # как в шаге 5.5
   docker image prune -f && docker builder prune -f
   ```
3. Повторить проверки шага 6.1.

## 8. Откат

1. **[VPS]** Вернуть в `deploy/.env.production` прежний тег (записан в шаге 7.2) и выполнить `$C up -d`.
   Старые образы остаются на сервере, пересборка не нужна.
2. Миграции базы при этом **не откатываются**. Если в неудачном релизе была миграция, откат делается
   только осознанно и вместе с разработчиком.

## Запрещено на проде

- `$C down -v` и `docker volume rm` — удаляют базу и сертификаты. Бэкапов базы пока нет.
- `docker image prune -a` — удаляет образы прошлых версий, откатываться станет не на что.
- Любые команды compose без `--env-file deploy/.env.production`.
- Пересоздание сервиса без `--no-deps`: вместе с ним пересоздаются postgres и redis.

## Если что-то пошло не так

| Симптом | Что сделать |
| --- | --- |
| `apt-get install docker-ce` падает с 403 или таймаутом | Хостинг или регион режет `download.docker.com`. Спросить в поддержке хостинга зеркало Docker. |
| `$C config` пишет `... is required` | Не заполнена названная переменная, шаг 4. |
| `$C build` падает с `Killed` или `exit code 137` | Не хватило памяти: проверить swap (`free -h`), повторить `$C build`. |
| `migrate-gamification` не `Exited (0)`, в логах `database "gamification" does not exist` | Том базы создан раньше, чем появился init-скрипт. На пустом сервере: `$C down` (**без** `-v`), затем разработчику — раздел «База данных в существующем томе» в `services/gamification/README.md`. |
| `users` или `gamification` не `healthy` | `$C logs users` / `$C logs gamification`; частая причина — ошибка в ключе подписи или секрете короче 32 символов. |
| Caddy не выпускает сертификат | Проверить `nslookup your-gamification.ru` → `77.232.135.105`, `sudo ufw status`, файрвол в панели хостинга. Не удалять том `caddy-data`. После исправления: `$C restart caddy` — один раз. |
| Сайт открывается, но API отвечает 502 | `$C restart web`. |
| Диск заполнен | `docker image prune -f && docker builder prune -f`, затем `df -h /`. |
