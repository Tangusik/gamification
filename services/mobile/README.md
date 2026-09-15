# Gamification — мобильное приложение

Flutter-клиент под Android. План и принятые решения — `.claude/plans/09-mobile-app.md`.
В оркестрацию (docker-compose, k8s) не входит. iOS отложен.

Flutter лежит в `C:\Users\kaver\ProgsMobile\flutter`, JDK для сборки — из Android Studio
(`flutter doctor -v` показывает путь).

## Адрес API

Задаётся при сборке: `--dart-define=API_BASE_URL=...`, без завершающего слэша.

| Где запускаем       | Адрес                                     |
| ------------------- | ----------------------------------------- |
| Эмулятор            | `http://10.0.2.2:8080/api/v1`             |
| Телефон по USB      | `http://127.0.0.1:8080/api/v1` + `adb reverse tcp:8080 tcp:8080` |
| Прод (release)      | `https://your-gamification.ru/api/v1`     |

Dev-стек (`docker-compose.dev.yml`) публикует `web` на `127.0.0.1:8080`. HTTP без TLS
разрешён только в debug-сборке, release ходит только по HTTPS.

## Запуск

```
flutter emulators --launch my_test
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8080/api/v1
```

Телефон по USB: включить отладку по USB, затем

```
%LOCALAPPDATA%\Android\Sdk\platform-tools\adb reverse tcp:8080 tcp:8080
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8080/api/v1
```

## Проверки

```
flutter analyze
flutter test
```

## Release APK

Подпись — своим keystore, который хранится вне репозитория. `android/key.properties`,
`*.jks` и `*.keystore` занесены в `.gitignore`. Если ключ потерять, обновить приложение
у пользователей не получится: придётся удалять его и ставить заново. Держите резервную
копию ключа.

1. Keystore создаётся один раз. `keytool` берётся из JDK Android Studio:
   ```
   "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe" -genkey -v -keystore C:\Users\kaver\keys\gamification-release.jks -keyalg RSA -keysize 2048 -validity 10000 -alias gamification
   ```
2. `android/key.properties`:
   ```
   storePassword=...
   keyPassword=...
   keyAlias=gamification
   storeFile=C:/Users/kaver/keys/gamification-release.jks
   ```
3. Перед каждой раздачей увеличить номер сборки `+N` в `version:` файла `pubspec.yaml`,
   иначе приложение не обновится поверх старой версии.
4. Сборка:
   ```
   flutter build apk --release --dart-define=API_BASE_URL=https://your-gamification.ru/api/v1
   ```
   Результат — `build/app/outputs/flutter-apk/app-release.apk`.
5. Проверка подписи:
   ```
   %LOCALAPPDATA%\Android\Sdk\build-tools\36.1.0\apksigner verify --print-certs build\app\outputs\flutter-apk\app-release.apk
   ```
6. Установка: `adb install -r app-release.apk` или передать файл на телефон и разрешить
   установку из неизвестных источников.
