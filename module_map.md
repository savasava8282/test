# Карта модулей проекта

Создана минимальная запускаемая Python-основа с безопасным слоем конфигурации и минимальным read-only подключением к Telegram Bot API. Настоящий токен в репозитории отсутствует; polling, обработка команд, внешние погодные API, база данных, планировщик и рассылки ещё не добавлены.

| Каталог или модуль | За что отвечает | Статус | Комментарий |
|---|---|---|---|
| `src/weather_alert_bot/` | Основной Python-пакет проекта | created | Пакет размещён по схеме `src` |
| `src/weather_alert_bot/__init__.py` | Обозначает каталог как Python-пакет | created | Не запускает интеграции |
| `src/weather_alert_bot/app.py` | Содержит функцию `main()`, минимальный вывод и `--check-telegram` | updated | Без аргументов сохраняет прежний вывод; проверка не запускает polling |
| `src/weather_alert_bot/__main__.py` | Поддерживает запуск пакета через `python3 -m weather_alert_bot` | created | Передаёт выполнение в `main()` |
| `src/weather_alert_bot/config.py` | Содержит неизменяемые `Settings`, ошибку `ConfigError` и загрузчик `load_settings()` | created | Читает токен только из окружения и скрывает его из `repr` |
| `src/weather_alert_bot/telegram_api.py` | Содержит `TelegramClient`, `TelegramBotIdentity` и `TelegramApiError` | created | Только `getMe`; токен не попадает в `repr` и тексты ошибок |
| `tests/` | Содержит автоматические проверки проекта | created | Используется только стандартный `unittest` |
| `tests/test_smoke.py` | Проверяет код возврата и точный текст минимального запуска | created | Внешние сервисы не используются |
| `tests/test_config.py` | Проверяет загрузку, обязательность и безопасное представление настройки токена | created | Используется только ненастоящее тестовое значение |
| `tests/test_telegram_api.py` | Проверяет client и `--check-telegram` | created | Mock-ответы, интернет и настоящий токен не используются |
