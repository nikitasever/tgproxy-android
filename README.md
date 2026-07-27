# TG Proxy Checker (Android)

Фоновое приложение: раз в 30 минут проверяет список MTProto-прокси
(с `http://<server_host>:8765/results.json`) настоящим MTProto-хендшейком
через ТЕКУЩУЮ сеть телефона (мобильную или Wi-Fi) и присылает уведомление
с рабочей ссылкой, как только находит проксирующий вариант.

Тап по уведомлению открывает `t.me/proxy?...` — подтверждение подключения
в самом Telegram убрать нельзя (это защита самого Telegram).

## Сборка

APK собирается автоматически через GitHub Actions (`.github/workflows/build.yml`)
при пуше в `main` или вручную (Actions → Build APK → Run workflow).
Готовый APK — в артефактах прогона.

Секреты репозитория (Settings → Secrets and variables → Actions):
- `TGPROXY_SERVER_HOST` — IP сервера с `results.json`
- `TGPROXY_HTTP_TOKEN` — токен для `/results.json?token=...`
- `TGPROXY_API_ID` / `TGPROXY_API_HASH` — твои Telegram API-ключи с my.telegram.org

## Установка на телефон

Скачать APK из артефактов Actions → включить "Установка из неизвестных
источников" для файлового менеджера/браузера → установить.
