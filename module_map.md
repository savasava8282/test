# Карта модулей проекта

Исходная точка задачи — commit `c7bebabfe61bbd5ae193fdb728369d97d0259166`. В этой задаче добавлен безопасный одноразовый сценарий `/start` на стандартной библиотеке Python. Настоящий токен Codex не читался; реальный запуск обработчика и отправка сообщения ещё не выполнялись.

| Каталог или модуль | За что отвечает | Статус | Комментарий |
|---|---|---|---|
| `src/weather_alert_bot/` | Основной Python-пакет проекта | created | Пакет размещён по схеме `src` |
| `src/weather_alert_bot/app.py` | CLI, обычный запуск, `--check-telegram` и `--wait-for-start` | updated | Два Telegram-режима взаимоисключающие; обычный запуск сохранён |
| `src/weather_alert_bot/__main__.py` | Запуск пакета через `python3 -m weather_alert_bot` | created | Передаёт выполнение в `main()` |
| `src/weather_alert_bot/config.py` | `Settings`, `ConfigError` и загрузчик окружения | created | Токен скрывается из `repr`; настоящий токен не читался |
| `src/weather_alert_bot/telegram_api.py` | `TelegramClient`, модели данных и безопасный API-слой | updated | Поддерживает `getUpdates`, `sendMessage` и прежний `getMe` |
| `src/weather_alert_bot/start_handler.py` | Однократное ожидание новой приватной `/start` | created | Очищает старые обновления, отвечает один раз и завершается |
| `tests/` | Автоматические проверки проекта | updated | Используются только стандартный `unittest` и mock |
| `tests/test_smoke.py` | Обычный CLI и сценарии `--wait-for-start` | updated | Реальные запросы не выполняются |
| `tests/test_config.py` | Безопасная загрузка настройки токена | updated | Используется только `123456789:TEST_TOKEN_NOT_REAL` |
| `tests/test_telegram_api.py` | `getMe`, `getUpdates`, `sendMessage` и ошибки | updated | HTTP вызывается только через mock |
| `tests/test_start_handler.py` | Очистка очереди, фильтрация, offset и остановка | created | Проверяет один ответ и `Ctrl+C` без traceback |

## Текущие границы реализации

- Погодная логика, NOAA, SQLite, выбор города, расписание, рассылки, постоянный polling, webhook и systemd не добавлены.
- Реальный запуск нового обработчика с Telegram ещё не выполнялся.
