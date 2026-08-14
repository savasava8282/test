# Карта модулей проекта

Исходная точка задачи геокодирования — commit `d4f455f26c59c9097c66124ae0d0ea2e67547a33`, независимо проверенный в GitHub; исходная точка реализации запроса города — commit `27745cfbfaa27525a0bda1aae008c8c9d30ef145`, а реализации `/start` — commit `733e616b944671e736531981bd8b9c5c70dafc09`. Перед реальным тестом HEAD совпадал с `origin/main`, рабочее дерево было чистым. В проекте сохранены безопасные одноразовые сценарии на стандартной библиотеке Python. Настоящий токен Codex не читался.

| Каталог или модуль | За что отвечает | Статус | Комментарий |
|---|---|---|---|
| `src/weather_alert_bot/` | Основной Python-пакет проекта | created | Пакет размещён по схеме `src` |
| `src/weather_alert_bot/app.py` | CLI, обычный запуск, существующие режимы, cache-aware `--preview-current-risks` и `--refresh-climate-cache` | updated | Все режимы взаимоисключающие; current-risks не требует Telegram и использует отдельный climate cache |
| `src/weather_alert_bot/geocoding.py` | Однократный Open-Meteo Geocoding API client и неизменяемая модель локации | created | Один GET-запрос без ключа, локальная проверка, безопасный JSON-разбор, без хранения и прогноза |
| `src/weather_alert_bot/__main__.py` | Запуск пакета через `python3 -m weather_alert_bot` | created | Передаёт выполнение в `main()` |
| `src/weather_alert_bot/config.py` | `Settings`, `ConfigError` и загрузчик окружения | updated | Токен скрывается из `repr`; settings DB и climate DB имеют отдельные paths/env overrides |
| `src/weather_alert_bot/storage.py` | SQLite-хранилище пользовательских настроек | updated | Только `sqlite3`; безопасно мигрирует `daily_send_time`, `daily_send_days`, `daily_sending_enabled`, `urgent_warnings_enabled`, восемь `warning_*_enabled` полей и `onboarding_completed` с default `07:00`, `1,2,3,4,5,6,7`, `1`, `1`, `1` и `0`, сохраняет upsert города без сброса настроек и отдельно обновляет время, дни, daily sending, срочные предупреждения, категории или completion flag по существующему `telegram_chat_id` |
| `src/weather_alert_bot/telegram_api.py` | `TelegramClient`, модели данных и безопасный API-слой | updated | Поддерживает `getUpdates`, `sendMessage` и прежний `getMe` |
| `src/weather_alert_bot/start_handler.py` | Однократное ожидание новой приватной `/start` | created | Очищает старые обновления без ответа, отвечает один раз и завершается; сценарий подтверждён контролируемым реальным запуском |
| `src/weather_alert_bot/city_handler.py` | Однократный запрос и локальная проверка города после новой `/start` | created | Реальный контролируемый запуск подтверждён; не хранит город, не вызывает внешние API, подтверждает один корректный текст и завершается |
| `src/weather_alert_bot/geocoded_city_handler.py` | Однократный Telegram-сценарий ввода, проверки и геокодирования города | created | Основной успешный сценарий подтверждён одним контролируемым реальным запуском Telegram + Open-Meteo; отправляет первый результат без хранения данных. Ошибки, пустой результат и Ctrl+C реально не проверялись |
| `src/weather_alert_bot/confirmed_city_handler.py` | Однократный Telegram-сценарий подтверждения найденного города | updated | После «Да» сохраняет подтверждённый `GeocodingLocation` через переданное хранилище и отправляет итоговый текст только после успешной записи; успешное сохранение подтверждено одним контролируемым реальным Telegram-тестом |
| `src/weather_alert_bot/daily_time_handler.py` | Однократная настройка локального времени ежедневной отправки | created | После новой приватной `/start` проверяет сохранённый город, принимает только `HH:MM`, сохраняет время без UTC-конвертации и безопасно завершается; подтверждён автоматическими тестами и одним контролируемым реальным Telegram-тестом |
| `src/weather_alert_bot/daily_days_handler.py` | Однократная настройка дней ежедневной отправки | created | После новой приватной `/start` проверяет сохранённый город, принимает канонизируемые номера `1`–`7`, сохраняет дни только для существующей строки и безопасно завершается; подтверждён автоматическими fake/mock-тестами и успешным контролируемым реальным Telegram-тестом |
| `src/weather_alert_bot/daily_sending_handler.py` | Однократная настройка включения ежедневной рассылки | created | После новой приватной `/start` проверяет сохранённый город, принимает `Да`/`Нет` без учёта регистра и с внешними пробелами, сохраняет boolean только для существующей строки и безопасно завершается; подтверждён автоматическими fake/mock-тестами и контролируемым реальным Telegram + SQLite-тестом |
| `src/weather_alert_bot/urgent_warnings_handler.py` | Однократная настройка включения срочных предупреждений | created | После новой приватной `/start` проверяет сохранённый город, принимает `Да`/`Нет` без учёта регистра и с внешними пробелами, сохраняет boolean только для существующей строки и безопасно завершается; подтверждён автоматическими fake/mock-тестами и успешным контролируемым реальным Telegram-тестом |
| `src/weather_alert_bot/warning_categories_handler.py` | Однократная настройка восьми категорий предупреждений | created | После новой приватной `/start` проверяет сохранённый город, принимает уникальные номера `1`–`8` или `0`, канонизирует выбор, сохраняет полный набор boolean-состояний только для существующей строки и безопасно завершается; подтверждён автоматическими fake/mock-тестами и реальным Telegram + SQLite-тестом |
| `src/weather_alert_bot/settings_summary_handler.py` | Однократная read-only итоговая сводка сохранённых onboarding-настроек | created | После новой приватной `/start` читает существующий `UserSettings`, отправляет стабильную сводку без записи в SQLite и безопасно завершается; автоматически проверен и подтверждён контролируемым реальным Telegram-тестом |
| `src/weather_alert_bot/onboarding_complete_handler.py` | Однократное финальное подтверждение и завершение первоначальной настройки | created | После новой приватной `/start` повторно показывает `format_settings_summary()`, принимает `Да`/`Нет`, при `Да` вызывает `mark_onboarding_completed()`, при `Нет` не меняет SQLite; автоматически проверен и подтверждён контролируемым реальным Telegram + SQLite-тестом обеих веток |
| `src/weather_alert_bot/today_handler.py` | Однократная обработка новой приватной `/today` владельца | created | Читает единственного владельца через переданное read-only storage, очищает старые updates без ответа, проверяет chat ID и onboarding, после корректной команды вызывает существующие weather/Kp clients и daily summary builder/formatter, отправляет один результат и завершается; real Telegram/API-тест ещё не выполнялся |
| `src/weather_alert_bot/climate_normals.py` | Historical Weather API client и pure calculation exact calendar-day ClimateNormals 1991–2020 | created | Полный snapshot из 366 calendar days, включая 29 February; raw historical dataset не является persistence format |
| `src/weather_alert_bot/climate_cache.py` | Отдельный SQLite cache рассчитанных ClimateNormals | created | Metadata/set identity, 366 day records, strict validation, corruption errors, atomic overwrite, read-only mode, multiple identities, explicit refresh и versioned schema; `user_settings` не используется |
| `src/weather_alert_bot/risk_assessment.py` | Pure/deterministic current-day risk assessment для восьми категорий при ClimateNormalDay | created | Immutable policy, signals и assessment; без climate normal сохраняется six-category compatibility mode |
| `tests/` | Автоматические проверки проекта | updated | Тесты геокодирования используют только стандартный `unittest` и mock; реальные сетевые вызовы не выполняются |
| `tests/test_smoke.py` | Обычный CLI и сценарии `--wait-for-start` | updated | Реальные запросы не выполняются |
| `tests/test_config.py` | Безопасная загрузка настройки токена | updated | Используется только `123456789:TEST_TOKEN_NOT_REAL` |
| `tests/test_telegram_api.py` | `getMe`, `getUpdates`, `sendMessage` и ошибки | updated | HTTP вызывается только через mock |
| `tests/test_start_handler.py` | Очистка очереди, фильтрация, offset и остановка | created | Проверяет один ответ и `Ctrl+C` без traceback |
| `tests/test_city_handler.py` | Сценарий запроса города, фильтрация, проверка текста и остановка | created | Проверяет старые обновления, новую `/start`, тот же чат, дубли и локальную валидацию |
| `tests/test_geocoding.py` | Клиент геокодирования, ошибки и CLI-вывод | created | Проверяет запрос, валидацию, JSON, mock-сеть, коды завершения и attribution |
| `tests/test_geocoded_city_handler.py` | Новый однократный Telegram-сценарий с геокодированием | created | Дополнительные ветки — пустой результат, ошибки, некорректный текст, другой чат, группы и `Ctrl+C` — проверяются только через fake/mock-тесты |
| `tests/test_storage.py` | Схема, миграция, upsert и изоляция настроек разных Telegram-чатов | updated | Проверяет `daily_send_time`, `daily_send_days`, `daily_sending_enabled`, `urgent_warnings_enabled`, все восемь `warning_*_enabled` полей, defaults, безопасную миграцию, нормализацию и сохранение настроек; использует только временные SQLite-базы |
| `tests/test_daily_time_handler.py` | Однократная настройка времени, валидация и Telegram-фильтрация | created | Проверяет корректные/некорректные значения, старые updates, группы, другой чат, отсутствие города и StorageError через fake/mock без настоящего Telegram token |
| `tests/test_daily_days_handler.py` | Однократная настройка дней, валидация и Telegram-фильтрация | created | Проверяет defaults, канонизацию, старые updates, группы, другой чат, отсутствие города, точные тексты, StorageError и `Ctrl+C` через fake/mock без настоящего Telegram token |
| `tests/test_urgent_warnings_handler.py` | Однократная настройка срочных предупреждений, валидация и Telegram-фильтрация | created | Проверяет `Да`/`Нет`, регистр, пробелы, некорректный ввод, старые updates, группы, другой чат, отсутствие города, точные тексты, StorageError и `Ctrl+C` через fake/mock |
| `tests/test_warning_categories_handler.py` | Однократная настройка категорий, валидация и Telegram-фильтрация | created | Проверяет prompt, all/subset/0, пробелы, канонизацию, все invalid-вводы, продолжение ожидания, старые updates, группы, другой чат, отсутствие города, StorageError и `Ctrl+C` через fake/mock |
| `tests/test_daily_sending_handler.py` | Однократная настройка daily sending, валидация и Telegram-фильтрация | created | Проверяет prompt, `Да`/`Нет`, регистр, пробелы, invalid с продолжением, очистку updates, группы, другой чат, отсутствие города, StorageError и `Ctrl+C` через fake/mock |

| `tests/test_settings_summary_handler.py` | Итоговая read-only сводка настроек и Telegram-фильтрация | created | Проверяет стабильный формат, дни, boolean-состояния, все/часть/ноль категорий, неизменность SQLite, очистку updates, группы, другой чат, отсутствие пользователя, StorageError и `Ctrl+C` через временную SQLite и fake/mock |
| `tests/test_onboarding_complete_handler.py` | Финальное подтверждение onboarding в Telegram | created | Проверяет summary-before-prompt, `Да`/`Нет`, регистр/пробелы, invalid continuation, updates, filtering, отсутствие города, StorageError и `KeyboardInterrupt` через временную SQLite и fake/mock |
| `tests/test_onboarding_storage.py` | Completion flag, add-only migration и storage API | created | Проверяет default `0`, миграцию только новой колонки, сохранение данных, идемпотентность, `0 -> 1`, отсутствие создания строки и сохранение флага при upsert города |
| `tests/test_onboarding_complete_cli.py` | CLI-режим финального подтверждения | created | Проверяет token-safe wiring, storage error, help и взаимоисключение с каждым существующим one-shot режимом и `--geocode-city` |
| `tests/test_today_handler.py` | One-shot `/today`, owner validation, data clients, formatter, ошибки и read-only поведение | created | Проверяет очистку старых updates, обе формы команды, private/group/чужие chats, onboarding, `daily_sending_enabled = 0`, safe errors, Telegram errors, fixed aware time, завершение и неизменность SQLite через fake/mock и временные базы |
| `tests/test_risk_assessment.py` | Current-day detector thresholds, local date, timezone conversion, statuses, stable signals и formatter | created | Fake immutable forecasts; покрывает шесть категорий, Kp mapping G1–G5, unsupported heat/cold и custom policy |
| `tests/test_risk_assessment_cli.py` | Diagnostic `--preview-current-risks` wiring и safe CLI behavior | created | Fake weather/Kp clients, read-only SQLite, отсутствие Telegram token, safe errors и mutual exclusion |
| `tests/test_climate_cache.py` | SQLite climate cache persistence, identity, validation и atomicity | created | Temporary SQLite; hit/miss primitives, overwrite, read-only, corruption, multiple identities и 366-day snapshots |
| `tests/test_climate_cache_cli.py` | Climate cache CLI orchestration и mutual exclusion | created | Fake Historical/weather/NOAA clients; cache miss/hit, refresh, settings read-only behavior и отсутствие real network |
| `tests/test_today_cli.py` | CLI-режим `--wait-for-today` | created | Проверяет обязательный token, read-only storage, existing clients, current aware datetime, help, safe storage error и mutual exclusion со всеми actions |

## Актуальный runtime-статус onboarding

- Контролируемый реальный Telegram + SQLite-тест `--wait-for-onboarding-complete` успешно завершён.
- Реальная миграция добавила `onboarding_completed` после backup `~/.local/share/weather-alert-bot/settings.before-onboarding-complete.sqlite3`; `cmp` подтвердил `Backup OK`.
- Реально подтверждены обе ветки: `Нет -> onboarding_completed = 0` без изменения остальных настроек и `Да -> onboarding_completed = 1` с успешным сообщением и штатным завершением one-shot.
- Автоматические тесты до реального теста: 236 успешно; `python3 -m compileall -q src` успешно. Scheduler, forecast, scheduled sending и systemd не начинались. `next_steps.md` отсутствует.

## Исторические границы реализации до commit `3007f15c2b9645de015691c9ceafb4e7a3ad1eeb`

Следующий список описывает состояние проекта до реализации сохранения подтверждённого города и не является текущим статусом.

- Погодная логика, NOAA, SQLite, выбор города, расписание, рассылки, постоянный polling, webhook и systemd не добавлены.
- Добавлен отдельный CLI-режим `--wait-for-city`: новая приватная `/start` вызывает просьбу о городе, затем принимается один локально корректный текст от того же чата и отправляется подтверждение.
- Добавлен отдельный однократный CLI-режим `--geocode-city CITY` через Open-Meteo Geocoding API; результаты основаны на GeoNames и ограничены пятью вариантами.
- Бесплатный endpoint допустим только для некоммерческого прототипа; коммерческая эксплуатация потребует подходящего платного тарифа или замены провайдера.
- Геокодирование интегрировано в однократный режим `--wait-for-geocoded-city`, не сохраняет город или координаты и не запрашивает прогноз погоды.
- Основной успешный сценарий `--wait-for-geocoded-city` подтверждён одним контролируемым реальным запуском Telegram + Open-Meteo: новая приватная `/start`, город «Москва», первый результат с регионом, страной, координатами `55.752040, 37.617810`, часовым поясом `Europe/Moscow` и attribution Open-Meteo и GeoNames. Ошибки, пустой результат и Ctrl+C реально не проверялись.
- Пользователь выполнил один контролируемый реальный запуск `PYTHONPATH=src python3 -m weather_alert_bot --geocode-city "Москва"`: Telegram-токен не требовался и не загружался, Telegram не вызывался, Open-Meteo вернул четыре подходящих варианта, первым была Москва, Москва, Россия.
- Результат содержал регион, страну, координаты и часовой пояс `Europe/Moscow`; приложение вывело не более пяти результатов и attribution Open-Meteo и GeoNames, без полного URL, необработанного JSON и traceback.
- Город и координаты не сохранялись, прогноз погоды не запрашивался; повторный реальный запрос в рамках этой документационной задачи не выполнялся.
- Город не сохраняется; существование города не проверяется; геокодирование доступно только отдельным CLI-режимом, погодные API, геолокация и кнопки Telegram не добавлены.
- Пользователь выполнил контролируемый реальный запуск `--wait-for-city`: токен был безопасно загружен во временной подсессии из `/root/.config/weather-alert-bot/env` и не попал в командную строку или вывод; старые обновления очищены без ответа, новая приватная `/start` обработана, отправлена просьба написать название города, принято одно сообщение с городом из того же приватного чата, отправлено подтверждение, пользователь подтвердил получение обоих сообщений в Telegram, после чего программа самостоятельно завершилась.
- Город не сохранялся и не проверялся; геокодирование, погодные API, постоянный polling, systemd и webhook не запускались. Повторный реальный запрос в рамках этой документационной задачи не выполнялся.
- `compileall` завершился без ошибок.
- Перед реальным запуском рабочий каталог был чистым, локальный `HEAD` совпадал с `origin/main`.
- Пользователь выполнил контролируемый реальный запуск `--wait-for-start`: токен был безопасно загружен во временной подсессии из `/root/.config/weather-alert-bot/env`, не попал в командную строку или вывод; старые обновления очищены без ответа, новая `/start` обработана, отправлено ровно одно фиксированное приветствие, пользователь подтвердил его получение в Telegram, после чего программа самостоятельно завершилась.
- Постоянная работа бота не запускалась; повторный реальный запрос в рамках этой документационной задачи не выполнялся.
- До этого контролируемого запуска все сетевые сценарии геокодирования проверялись через mock; успешно прошли 56 автоматических тестов, `compileall` завершился без ошибок.

## Историческая запись о реальном тесте `--wait-for-confirmed-city`

- Контролируемый запуск выполнен из `/root/projects/test` командой `set -a; source /root/.config/weather-alert-bot/env; set +a; PYTHONPATH=src python3 -m weather_alert_bot --wait-for-confirmed-city`; секреты не читались и не выводились.
- В Telegram реально пройдена цепочка: новая `/start`, ввод «Москва», геокодирование, найденный вариант, подтверждение «Да».
- Финальное Telegram-сообщение подтверждено точно: `Город подтверждён.` и `Город пока не сохранён.`
- После повторного подключения `pgrep -af "weather_alert_bot"` ничего не вывел и сразу вернул shell prompt; процесс после теста больше не был запущен.
- SSH disconnect (`client_loop: send disconnect: Connection reset`) ограничил наблюдение старой SSH-сессии: финальные строки терминала непосредственно не наблюдались. Это не записывается как ошибка приложения; строки `Город подтверждён.` и `Подтверждение отправлено.` не заявляются как увиденные в терминале.
- Следующий функциональный этап — сохранение подтверждённого города, координат и часового пояса. В текущем run он не начинался.

## Историческая запись о реализации `--wait-for-confirmed-city`

- Исходный commit задачи: `87bd639e857e645ce795c41274f2ffd3a03ba586`.
- `src/weather_alert_bot/confirmed_city_handler.py` | отдельный однократный Telegram-сценарий подтверждения первого результата Open-Meteo; не сохраняет город, координаты или часовой пояс.
- `src/weather_alert_bot/app.py` | добавлен `--wait-for-confirmed-city` во взаимоисключающую группу; существующий `--wait-for-geocoded-city` сохранён.
- `tests/test_confirmed_city_handler.py` | fake/mock-проверки очистки обновлений, фильтрации, геокодирования, подтверждения, отказа, ошибок, безопасности вывода и `Ctrl+C`.
- Новый режим показывает первый найденный вариант и спрашивает «Да» или «Нет»; при «Нет» возвращается к вводу города без повторной `/start`.
- Прогноз погоды, API-ключ, SQLite, постоянный polling, systemd, расписание и рассылки не добавлены. Реальный Telegram-запуск нового режима выполнен и описан ниже; настоящий токен Codex не читался.

## Детали реализации сохранения после commit `3007f15c2b9645de015691c9ceafb4e7a3ad1eeb`

- Создан `src/weather_alert_bot/storage.py` на стандартном `sqlite3`; таблица `user_settings` хранит `telegram_chat_id` как первичный ключ, город, latitude, longitude и timezone.
- `SQLiteSettingsStore` создаёт родительский каталог при инициализации и использует безопасный upsert; импорт модулей SQLite-файл не создаёт.
- `config.py` добавляет `WEATHER_ALERT_BOT_DB_PATH`; по умолчанию используется `~/.local/share/weather-alert-bot/settings.sqlite3`.
- CLI `--wait-for-confirmed-city` создаёт хранилище по конфигурации и передаёт его handler. При «Да» сохраняется именно подтверждённый кандидат Open-Meteo; «Нет», некорректный ответ, ошибка геокодирования и отсутствие совпадений запись не создают.
- После успешного сохранения Telegram получает точно `Город подтверждён.\n\nГород сохранён.`; ошибка SQLite даёт безопасное сообщение и код завершения `1`, без ложного сообщения об успехе.
- На момент этого commit автоматические тесты использовали временные SQLite-базы, а реальный Telegram-тест новой логики сохранения ещё не выполнялся; это историческое состояние.
- Настройка времени рассылки, дней недели, прогноз и другие этапы тогда не начинались.

## Историческая запись после настройки времени ежедневной отправки

- SQLite-хранилище реализовано на стандартном `sqlite3`; используется таблица `user_settings` с `telegram_chat_id PRIMARY KEY`.
- После «Да» сохраняются `city_name`, `latitude`, `longitude` и `timezone` подтверждённого кандидата; для существующего chat ID выполняется upsert.
- По умолчанию используется `~/.local/share/weather-alert-bot/settings.sqlite3`; `WEATHER_ALERT_BOT_DB_PATH` задаёт другой путь.
- Сохранение города остаётся подтверждённым автоматическими тестами и одним контролируемым реальным Telegram-тестом; пользовательское поведение `--wait-for-confirmed-city` не менялось.
- В `user_settings` добавлено `daily_send_time` с default `07:00`; старая схема мигрируется безопасным добавлением колонки без удаления данных.
- `save_confirmed_city()` сохраняет пользовательское время при повторной смене города. `save_daily_send_time()` обновляет только существующую строку и не создаёт пользователя без города.
- Новый `--wait-for-daily-time` очищает старые updates, принимает новую приватную `/start`, проверяет город и сохраняет локальное время `HH:MM` относительно сохранённого timezone без UTC-конвертации.
- Новый режим подтверждён автоматическими тестами и одним контролируемым реальным Telegram-тестом; точные сообщения и результаты миграции зафиксированы ниже.
- Полный набор автоматических тестов: 110 тестов успешно; `python3 -m compileall -q src` успешно.
- Дни недели, планировщик, прогноз погоды, отправка прогноза по расписанию и systemd не реализованы. `next_steps.md` отсутствует.
- Исторический stop-point на тот момент: `--wait-for-daily-time` и безопасная миграция существующей SQLite-базы реально подтверждены; следующий функциональный этап не начинался.

### Доказательства реального теста `--wait-for-daily-time`

- До запуска read-only проверка подтвердила старую схему без `daily_send_time`; ранний ошибочный smoke-тест реальную базу не мигрировал.
- До миграции создана резервная копия `~/.local/share/weather-alert-bot/settings.before-daily-time.sqlite3`; `cmp` подтвердил `Backup OK`. Backup в Git не добавлялся.
- Telegram prompt: `Во сколько отправлять ежедневную сводку? Введите время в формате ЧЧ:ММ. По умолчанию — 07:00.`
- После ввода `08:30` Telegram success: `Время ежедневной отправки сохранено: 08:30.`
- Четыре строки терминала:

  ```text
  Ожидание новой команды /start...
  Команда /start получена.
  Ожидание времени ежедневной отправки...
  Время ежедневной отправки сохранено.
  ```

- Реальная миграция добавила `daily_send_time`; read-only проверка после запуска подтвердила `city_name = Москва`, `latitude = 55.75204`, `longitude = 37.61781`, `timezone = Europe/Moscow`, `daily_send_time = 08:30`.
- Процесс штатно завершился. Telegram chat ID, token и содержимое env не документируются. Дни недели, scheduler, forecast, scheduled sending и systemd не реализованы; `next_steps.md` отсутствует.

## Историческая запись перед реальным тестом `--wait-for-daily-days`

- `user_settings.daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7'` реализован; хранится каноническая строка номеров дней через запятую, по возрастанию, без названий дней.
- Новая база сразу создаёт обе настройки времени и дней. Существующая схема с `daily_send_time` мигрируется только через безопасный `ALTER TABLE ... ADD COLUMN daily_send_days ...`; более старая схема без `daily_send_time` по-прежнему проходит миграцию времени. Миграция идемпотентна и не пересоздаёт таблицу.
- Автотест миграции подтвердил сохранение города `Москва`, `55.75204`, `37.61781`, `Europe/Moscow` и пользовательского `daily_send_time = 08:30`; добавленная строка получает все семь дней. Реальная база в этом run не использовалась.
- `save_confirmed_city()` не сбрасывает ни `daily_send_time`, ни `daily_send_days`; `save_daily_send_days()` нормализует ввод и обновляет только существующего пользователя.
- Добавлены `normalize_daily_send_days()`, `daily_days_handler.py` и CLI `--wait-for-daily-days`, взаимоисключающийся со всеми существующими режимами. Некорректные номера, пустой ввод, команды, названия, диапазоны и дубли отклоняются.
- Новый режим подтверждён 132 автоматическими тестами с временными SQLite-базами и fake/mock Telegram; `python3 -m compileall -q src` успешен. Реальный Telegram-тест ещё не выполнялся.
- Исторический stop-point на тот момент: хранение и отдельная однократная настройка дней были реализованы и автоматически проверены; реальный Telegram-тест дней ещё не выполнялся. Scheduler, forecast, scheduled sending, urgent warnings и systemd не реализованы. `next_steps.md` отсутствует.

## Историческая запись после реального теста `--wait-for-daily-days`

- До запуска read-only проверка фактической SQLite-базы показала схему без `daily_send_days`: `telegram_chat_id`, `city_name`, `latitude`, `longitude`, `timezone`, `daily_send_time`. Реальные данные: `Москва`, `55.75204`, `37.61781`, `Europe/Moscow`, `08:30`.
- Перед миграцией создан backup `~/.local/share/weather-alert-bot/settings.before-daily-days.sqlite3`; `cmp` подтвердил `Backup OK`. Backup в Git не добавлялся.
- Реальный запуск выполнен командой `set -a; source /root/.config/weather-alert-bot/env; set +a; PYTHONPATH=src python3 -m weather_alert_bot --wait-for-daily-days`. После запуска терминал показал `Ожидание новой команды /start...`.
- После новой приватной `/start` Telegram прислал prompt: `В какие дни отправлять ежедневную сводку? Введите номера дней через запятую: 1=Пн, 2=Вт, 3=Ср, 4=Чт, 5=Пт, 6=Сб, 7=Вс. По умолчанию — каждый день.`; терминал показал `Команда /start получена.` и `Ожидание дней ежедневной отправки...`.
- Ввод `1,1` реально отклонён точным сообщением `Некорректные дни. Введите номера от 1 до 7 через запятую, например: 1,2,3,4,5.`; режим продолжил ждать ввод.
- Ввод `5,1,3` реально сохранён: Telegram ответил `Дни ежедневной отправки сохранены: Пн, Ср, Пт.`, терминал вывел `Дни ежедневной отправки сохранены.`
- Процесс штатно завершился и вернул shell prompt. После теста read-only проверка подтвердила схему с `daily_send_days` и данные `Москва`, `55.75204`, `37.61781`, `Europe/Moscow`, `08:30`, `daily_send_days = 1,3,5`.
- Исторический stop-point на тот момент: город, время `08:30` и дни `1,3,5` реально проверены; безопасная миграция, отказ дублей, продолжение ожидания после ошибки, нормализация порядка и русское отображение подтверждены. Следующий функциональный этап ещё не начинался. Scheduler, forecast, scheduled sending, urgent warnings и systemd не реализованы. `next_steps.md` отсутствует.

## Историческая запись после реализации сохранения срочных предупреждений

- `storage.py` расширяет `user_settings` полем `urgent_warnings_enabled INTEGER NOT NULL DEFAULT 1`; `1` — включено, `0` — выключено. Новая база создаёт поле сразу.
- Для схемы с `daily_send_time` и `daily_send_days` выполняется только недеструктивный `ALTER TABLE ... ADD COLUMN urgent_warnings_enabled`; более старые схемы проходят последовательную безопасную миграцию недостающих полей. Миграция идемпотентна и не теряет строки или прежние значения.
- `UserSettings.urgent_warnings_enabled` — `bool`; `get_user_settings()` преобразует SQLite `0/1`. `save_urgent_warnings_enabled()` принимает только boolean, не создаёт пользователя без города и не меняет остальные настройки. Upsert города сохраняет это значение.
- Добавлены `urgent_warnings_handler.py` и взаимоисключающий CLI `--wait-for-urgent-warnings`. Fake/mock-тестами подтверждены точные Telegram-тексты, регистр и пробелы, отказ некорректного ввода с продолжением ожидания, очистка старых updates, фильтрация групп и других чатов, отсутствие города, безопасные StorageError и `KeyboardInterrupt`.
- 152 автоматических теста успешно; `python3 -m compileall -q src` успешно. Тесты используют только временные SQLite-базы или mock; реальная пользовательская база не открывалась.
- Реальный Telegram-тест нового режима на тот момент ещё не выполнялся. Ранее реально подтверждённые `daily_send_time = 08:30` и `daily_send_days = 1,3,5` сохранялись как доказанное состояние.

## Историческая запись после контролируемого реального теста `--wait-for-urgent-warnings`

- Тест выполнен поверх commit `58bae9a77033961b8c373ec4c61c5c4c4595c5bd`. До миграции read-only схема была `telegram_chat_id`, `city_name`, `latitude`, `longitude`, `timezone`, `daily_send_time`, `daily_send_days`; строка содержала `Москва`, `55.75204`, `37.61781`, `Europe/Moscow`, `08:30`, `1,3,5`. `urgent_warnings_enabled` отсутствовало.
- Создан backup `~/.local/share/weather-alert-bot/settings.before-urgent-warnings.sqlite3`; `cmp` подтвердил `Backup OK`. Backup в Git не добавлялся.
- Первый запуск `--wait-for-urgent-warnings` показал `Ожидание новой команды /start...`. После новой приватной `/start` Telegram прислал `Включить срочные предупреждения? По умолчанию — включены. Ответьте: Да или Нет.`; терминал показал `Команда /start получена.` и `Ожидание настройки срочных предупреждений...`.
- Ввод `yes` реально отклонён сообщением `Некорректный ответ. Введите: Да или Нет.`; процесс продолжил ожидание. Ввод `Нет` дал `Срочные предупреждения выключены.`, терминал показал `Настройка срочных предупреждений сохранена.`, а read-only строка стала `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 0)` при схеме с `urgent_warnings_enabled`.
- Второй запуск того же режима с вводом `Да` дал `Срочные предупреждения включены.` и штатно завершился; финальная read-only схема была `['telegram_chat_id', 'city_name', 'latitude', 'longitude', 'timezone', 'daily_send_time', 'daily_send_days', 'urgent_warnings_enabled']`, строка стала `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 1)`. Оба успешных запуска завершились нормально; итоговое состояние — включено. Telegram chat ID, token и содержимое env не документируются.

## Историческая запись после реального теста срочных предупреждений

- Город, `daily_send_time = 08:30`, `daily_send_days = 1,3,5` и `urgent_warnings_enabled = 1` реально проверены.
- Контролируемый реальный тест подтвердил invalid `yes` с продолжением ожидания, `Нет -> 0` и `Да -> 1`.
- Warning categories НЕ реализованы; scheduler, forecast, scheduled sending и systemd НЕ начинались.
- Следующий безопасный функциональный этап — warning categories согласно `technical_spec.md`; `next_steps.md` отсутствует.

## Историческая запись после реализации persistent warning categories

- `storage.py` добавляет восемь явных `warning_*_enabled INTEGER NOT NULL DEFAULT 1` полей, bool-поля в `UserSettings`, стабильные внутренние category keys и `save_warning_categories()`; миграции идемпотентны, add-only и сохраняют текущие настройки пользователя.
- Добавлен `warning_categories_handler.py` и взаимоисключающий CLI `--wait-for-warning-categories`. Он принимает уникальные номера `1`–`8` или `0`, отклоняет malformed/duplicate/mixed-zero/text input, выдаёт утверждённые русские тексты и не раскрывает внутренние ошибки.
- Полный набор автоматических тестов: 176 тестов успешно; `python3 -m compileall -q src` успешно. Использованы только временные SQLite-базы и fake/mock Telegram. Реальный Telegram-тест категорий ещё НЕ выполнялся.

## Исторический stop-point после реализации warning-category settings

- Реально подтверждены ранее: `Москва`, `55.75204`, `37.61781`, `Europe/Moscow`, `daily_send_time = 08:30`, `daily_send_days = 1,3,5`, `urgent_warnings_enabled = 1`.
- Восемь category settings, defaults, migrations, storage API и `--wait-for-warning-categories` реализованы, автоматически проверены и подтверждены реальным Telegram + SQLite-тестом.
- Реальная миграция добавила отсутствовавшие восемь category-колонок без потери старых настроек. Backup `~/.local/share/weather-alert-bot/settings.before-warning-categories.sqlite3` проверен через `cmp` с результатом `Backup OK`.
- Реально подтверждены prompt выбора категорий, отказ дубля `1,1` с продолжением ожидания, сохранение `8,1,3`, отключение всех категорий вводом `0`, включение всех категорий вводом `1,2,3,4,5,6,7,8` и штатное завершение каждого one-shot запуска.
- Финальное состояние реальной базы — все восемь категорий включены; `Москва`, `55.75204`, `37.61781`, `Europe/Moscow`, `08:30`, `1,3,5` и `urgent_warnings_enabled = 1` сохранены.
- Исторический stop-point на тот момент: scheduler, forecast, scheduled sending и systemd не начинать; `next_steps.md` отсутствует.

## Историческая запись реального теста warning categories

- Реальный режим запускался командой `set -a; source /root/.config/weather-alert-bot/env; set +a; PYTHONPATH=src python3 -m weather_alert_bot --wait-for-warning-categories`; после новой приватной `/start` бот показал реальный prompt выбора категорий.
- `1,1` получил точную ошибку `Некорректные категории. Введите уникальные номера от 1 до 8 через запятую или 0, чтобы отключить все.`; ожидание продолжилось.
- `8,1,3` дал `Категории предупреждений сохранены: Магнитная буря, Холод, Шторм.` и терминальное `Категории предупреждений сохранены.`; SQLite показала `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 1, 1, 0, 1, 0, 0, 0, 0, 1)`.
- Ветка `0` дала `Все категории предупреждений отключены.`, штатное завершение и восемь нулей в SQLite без изменения остальных настроек. Ввод `1,2,3,4,5,6,7,8` включил все категории; финальная SQLite-строка: `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 1, 1, 1, 1, 1, 1, 1, 1, 1)`.

## Историческая запись перед реальным тестом persistent daily-sending setting

- Реализованы `daily_sending_enabled INTEGER NOT NULL DEFAULT 1`, `UserSettings.daily_sending_enabled`, `save_daily_sending_enabled()`, `daily_sending_handler.py`, `run_until_daily_sending()` и CLI `--wait-for-daily-sending`.
- Миграция add-only и идемпотентна; повторный upsert города сохраняет daily-sending state. Полный набор автоматических тестов: 196 успешных тестов; реальный Telegram + SQLite-тест нового setting ещё не выполнялся.
- На тот момент следующим безопасным шагом был только контролируемый реальный Telegram + SQLite-тест daily-sending setting. Scheduler, forecast, scheduled sending и systemd не начинать; `next_steps.md` отсутствует.

## Историческая запись после успешно завершённого реального теста daily sending

- До миграции в `user_settings` не было `daily_sending_enabled`; фактический список колонок был `['telegram_chat_id', 'city_name', 'latitude', 'longitude', 'timezone', 'daily_send_time', 'daily_send_days', 'urgent_warnings_enabled', 'warning_magnetic_storm_enabled', 'warning_heat_enabled', 'warning_cold_enabled', 'warning_icing_enabled', 'warning_heavy_rain_enabled', 'warning_thunderstorm_enabled', 'warning_strong_wind_enabled', 'warning_storm_enabled']`.
- Перед запуском создан backup `~/.local/share/weather-alert-bot/settings.before-daily-sending.sqlite3`; `cmp` дал `Backup OK`. Реальный запуск выполнялся командой `set -a; source /root/.config/weather-alert-bot/env; set +a; PYTHONPATH=src python3 -m weather_alert_bot --wait-for-daily-sending`.
- После новой приватной `/start` бот отправил prompt `Включить ежедневную рассылку? По умолчанию — включена. Ответьте: Да или Нет.`; терминал показал `Команда /start получена.` и `Ожидание настройки ежедневной рассылки...`.
- Реальный `yes` получил `Некорректный ответ. Введите: Да или Нет.`, после чего ожидание продолжилось. `Нет` дал `Ежедневная рассылка выключена.`, терминал — `Настройка ежедневной рассылки сохранена.`, а one-shot процесс штатно завершился.
- Read-only SQLite-проверка после `Нет` показала `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 0, 1, 1, 1, 1, 1, 1, 1, 1, 1)`.
- Повторный запуск той же командой и ответ `Да` дали `Ежедневная рассылка включена.` и `Настройка ежедневной рассылки сохранена.`; процесс снова штатно завершился. Финальная read-only строка: `('Москва', 55.75204, 37.61781, 'Europe/Moscow', '08:30', '1,3,5', 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)`.
- Реально подтверждены миграция существующей SQLite без потери данных, invalid input с продолжением ожидания, `Нет -> 0`, `Да -> 1`, штатное завершение one-shot режима и сохранение города, координат, timezone, времени, дней, urgent setting и всех восьми warning category flags. Финальное `daily_sending_enabled = 1`.

### Исторический stop-point на тот момент

Daily-sending implementation и контролируемый реальный Telegram + SQLite-тест успешно завершены. Scheduler, получение прогноза, scheduled sending и systemd ещё НЕ начинались; `next_steps.md` отсутствует.

## Историческая запись перед контролируемым реальным тестом итоговой сводки

- Добавлены `settings_summary_handler.py`, `run_until_settings_summary()` и взаимоисключающий CLI-режим `--wait-for-settings-summary`.
- Режим очищает старые updates, ждёт новую приватную `/start` или `/start@weather_storm_alert_bot`, игнорирует группы и другие чаты, читает сохранённый `UserSettings`, ничего не записывает в SQLite и после одной успешной отправки завершается.
- Стабильная сводка содержит город, время, русские дни отправки, состояния daily sending и urgent warnings и включённые категории; при отсутствии пользователя и `StorageError` отправляются безопасные сообщения.
- Автоматически прошли 214 тестов; на тот момент реальный Telegram-тест нового режима ещё не выполнялся. `python3 -m compileall -q src` успешно.

### Исторический stop-point на тот момент

Следующим безопасным шагом был контролируемый реальный Telegram-тест `--wait-for-settings-summary`. Scheduler, forecast, scheduled sending и systemd не начинать; `next_steps.md` отсутствует.

## Актуальная запись после успешно завершённого реального теста итоговой сводки

- Реализация `--wait-for-settings-summary` завершена; handler остаётся read-only и не вызывает API сохранения настроек.
- Контролируемый реальный запуск выполнен командой `set -a; source /root/.config/weather-alert-bot/env; set +a; PYTHONPATH=src python3 -m weather_alert_bot --wait-for-settings-summary`.
- После новой приватной `/start` отправлен точный итоговый текст с городом `Москва`, временем `08:30`, днями `Пн, Ср, Пт`, включённой ежедневной рассылкой, включёнными срочными предупреждениями и всеми восемью категориями в русском каноническом порядке.
- Терминал подтвердил `Ожидание новой команды /start...`, затем `Команда /start получена.` и `Итоговая сводка настроек отправлена.`; one-shot процесс штатно завершился и вернул shell prompt.
- Отдельная byte-for-byte проверка SQLite после запуска не выполнялась; реальный тест подтверждает Telegram-сценарий, а не независимое сравнение базы.
- Пункт 10 первоначальной настройки — показ итоговых настроек — подтверждён; пункт 11 и onboarding целиком автоматически завершёнными не объявлять.
- Полный набор автоматических тестов — 214 успешных тестов; `python3 -m compileall -q src` успешно. Scheduler, forecast, scheduled sending и systemd не начинать; `next_steps.md` отсутствует.

## Историческая запись после добавления weather forecast data layer, до реального Open-Meteo-теста

- `src/weather_alert_bot/weather_forecast.py` — изолированный Open-Meteo Weather Forecast API client: запрос на 5 суток с сохранёнными координатами и timezone, безопасный разбор daily/hourly ответа, immutable-модели `WeatherForecast`, `DailyForecast`, `HourlyForecast` и `WeatherForecastError`.
- `src/weather_alert_bot/storage.py` — добавлен read-only режим `SQLiteSettingsStore(..., read_only=True)` и `get_single_user_settings()` для диагностического сценария единственного владельца; при нескольких строках выдаётся безопасная `StorageError`.
- `src/weather_alert_bot/app.py` — добавлен взаимоисключающий `--fetch-weather-forecast`; он читает config/SQLite, вызывает weather client с сохранёнными latitude/longitude/timezone и печатает только компактные диагностические поля.
- `tests/test_weather_forecast.py` — mock HTTP, параметры URL, timezone, `forecast_days=5`, модели и безопасное отклонение некорректных ответов/ошибок.
- `tests/test_weather_forecast_cli.py` — read-only storage API, единственный/отсутствующий/неоднозначный владелец, wiring CLI, неизменность SQLite, безопасная ошибка weather client и взаимоисключение действий.
- Всего автоматически пройдено 255 тестов; `technical_spec.md` не изменён; `next_steps.md` отсутствует.
- Реальный Open-Meteo-запрос новым кодом ещё не выполнялся. Telegram weather summary, Kp, scheduler, scheduled sending и systemd не реализованы.

Следующий stop-point: только контролируемая реальная проверка `--fetch-weather-forecast` с Open-Meteo. Следующий архитектурный этап не выбирать автоматически.

## Актуальное состояние после успешно завершённого реального Open-Meteo-теста

- `src/weather_alert_bot/weather_forecast.py` реально выполнил запрос Open-Meteo для сохранённого города `Москва` и timezone `Europe/Moscow`; получены 5 daily-дней и 120 hourly-значений (`5 × 24`). Daily и hourly данные успешно разобраны.
- `src/weather_alert_bot/app.py` — `--fetch-weather-forecast` вывел компактные обработанные поля: город, timezone, число дней, первую дату, min/max, осадки, ветер, порывы и количество hourly points. Сырой JSON не выводился.
- Реальная SQLite `~/.local/share/weather-alert-bot/settings.sqlite3` не изменилась: SHA-256 до запроса `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`, после запроса — та же `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`.
- Реальный Telegram-запрос в рамках weather forecast теста не выполнялся. До теста были зафиксированы 255 успешных автоматических тестов, успешный compileall, чистый `git diff --check`, отсутствие secrets/`.env`/SQLite/backup-файлов в Git и отсутствие `next_steps.md`; автоматические тесты после real API не запускались.
- Форматирование пользовательской ежедневной Telegram-сводки, магнитные бури/Kp, климатическая норма, weather warning logic, scheduler, scheduled sending и systemd ещё не реализованы.

Следующий stop-point: weather layer подтверждён на реальном API. Следующий архитектурный этап должен быть отдельно выбран техническим лидом; к scheduler автоматически не переходить.

## Историческая запись после первоначальной реализации NOAA SWPC Kp forecast data layer, до первого real API-теста и исправления формата

- `src/weather_alert_bot/geomagnetic_forecast.py` — официальный NOAA SWPC client для `noaa-planetary-k-index-forecast.json`, header-aware parser табличного JSON, immutable-модели `GeomagneticForecast`/`GeomagneticForecastInterval` и `GeomagneticForecastError`. Parser сохраняет timestamp, Kp, status/type и optional issue/update time без G-level бизнес-логики.
- `src/weather_alert_bot/app.py` — взаимоисключающий `--fetch-kp-forecast`; режим не требует Telegram token, не открывает SQLite и печатает источник, количество интервалов, границы времени, первый/максимальный Kp и status breakdown.
- `tests/test_geomagnetic_forecast.py` — fake HTTP для endpoint, timeout, header/columns, табличных строк, timestamp/Kp/status, optional issue time и всех обязательных malformed/error cases.
- `tests/test_geomagnetic_forecast_cli.py` — compact CLI output, отсутствие зависимости от Telegram/SQLite, безопасная `GeomagneticForecastError` и взаимоисключение со всеми actions.
- Полный автоматический набор: 271 тест успешно; compileall успешно. Реальный NOAA SWPC запрос новым кодом ещё не выполнялся.
- Weather forecast data layer остаётся real-tested на Open-Meteo API. Telegram daily summary, G-level/warning logic, climate norms, weather warning logic, scheduler, scheduled sending и systemd не реализованы.

Следующий stop-point: только контролируемый реальный `--fetch-kp-forecast`. Следующий архитектурный этап выбирается отдельно техническим лидом.

## Историческая запись после исправления фактического NOAA object-list format, до повторного real-теста

- `src/weather_alert_bot/geomagnetic_forecast.py` — parser теперь принимает официальный фактический `list[dict]` response NOAA SWPC, требует `time_tag`, numeric `kp` и строковый `observed`, сохраняет nullable/string `noaa_scale`, не придумывает timezone и не выполняет G-level mapping.
- Первый real CLI test завершился `Ошибка получения прогноза Kp NOAA SWPC.`; отдельная endpoint-проверка подтвердила HTTP 200 и JSON, а диагностика показала 81 object-запись. Причина — первоначальное неверное ожидание tabular header/list format.
- `tests/test_geomagnetic_forecast.py` — success fixtures переведены на object-list и добавлены regression/error cases для actual records, fractional Kp `2.33`, null/string `noaa_scale`, обязательных полей и malformed values.
- После fix полный автоматический набор: 273 теста успешно; compileall успешно. Повторный реальный NOAA-запрос после fix ещё не выполнялся.
- `--fetch-kp-forecast` остаётся one-shot diagnostic CLI без Telegram token, SQLite и business warning logic.

Следующий stop-point: только повторный контролируемый реальный `--fetch-kp-forecast`; Kp layer до него не считать real-tested.

## Актуальное состояние после успешно завершённого real NOAA SWPC-теста

- `src/weather_alert_bot/geomagnetic_forecast.py` подтверждён на официальном NOAA SWPC endpoint после исправления формата: object-list parser обработал 81 интервал, `time_tag`, дробные Kp и статусы `estimated`, `observed`, `predicted`.
- `--fetch-kp-forecast` реально вывел:

  ```text
  Источник: NOAA SWPC
  Количество интервалов: 81
  Первый timestamp: 2026-08-04 00:00:00
  Последний timestamp: 2026-08-14 00:00:00
  Первый Kp: 4
  Максимальный Kp: 5.67
  Статусы: estimated=3, observed=61, predicted=17
  ```

- Первый real-test до исправления завершился `GeomagneticForecastError`, хотя endpoint отдельно отвечал `200 application/json`; причиной был ошибочный tabular parser. После диагностики `list[dict]` parser и regression fixtures исправлены, затем повторный real-test успешно завершён.
- Полный автоматический набор после исправления: 273 теста успешно; compileall успешно. CLI не требует Telegram и не использует SQLite.
- Telegram daily summary, `/today`, G1–G5 warning/business logic, пользовательский Kp threshold, NOAA watches/warnings/alerts, climate norms, weather warning logic, scheduler, scheduled sending и systemd не реализованы.

Weather forecast data layer и Kp forecast data layer подтверждены реальными API. Следующий архитектурный этап выбирается отдельно техническим лидом.

## Актуальное состояние после реализации base daily summary layer

- `src/weather_alert_bot/daily_summary.py` — pure/deterministic builder `build_daily_summary(...)`, immutable `DailySummary`, `DailySummaryError` и стабильный `format_daily_summary(...)`; HTTP clients отсутствуют внутри formatter/business layer.
- Builder использует сохранённый timezone через `ZoneInfo`, выбирает текущий local date, точные `09:00`/`15:00`, явную WMO mapping, deterministic precipitation-time convention и максимум первых 8 `predicted` Kp intervals.
- `src/weather_alert_bot/app.py` — добавлен взаимоисключающий `--preview-daily-summary`; он читает единственного владельца через существующий read-only storage API, вызывает существующие weather/Kp clients и печатает итоговый текст без Telegram.
- `tests/test_daily_summary.py` — timezone/date selection, exact hourly points, WMO codes, precipitation rules, formatting, Kp predicted window и ошибки.
- `tests/test_daily_summary_cli.py` — fake clients, read-only SQLite, отсутствие Telegram token, safe errors и CLI mutual exclusion.
- Полный набор: 292 теста успешно; compileall успешно. Реальный `--preview-daily-summary` ещё не выполнялся.
- Climate norms, warnings/risk, G1–G5, `/today`, Telegram send, scheduler, scheduled sending и systemd не реализованы.

Следующий stop-point: только контролируемый real preview на существующих настройках через Open-Meteo + NOAA; следующий архитектурный этап отдельно выбирает технический лидер.

## Актуальная запись после успешно завершённого real `--preview-daily-summary`

- `src/weather_alert_bot/app.py` — diagnostic one-shot `--preview-daily-summary` реально выполнен на сохранённых настройках города `Москва`; Telegram-запрос не выполнялся, SQLite осталась read-only.
- Существующий weather data layer реально получил weather-часть через Open-Meteo, а существующий Kp data layer — Kp-часть через NOAA SWPC.
- `src/weather_alert_bot/daily_summary.py` — local date/time formatter сработал для сохранённого timezone `Europe/Moscow`; реальные данные успешно применили правила `09:00` для утра и `15:00` для дня.
- Реальная precipitation presentation сформировала `до 53%, наиболее вероятно около 08:00`; Kp presentation сформировала `Kp до 2 в ближайшие 24 ч`.
- До real-test были успешно пройдены 292 автоматических теста. Полный фактический diagnostic preview:

  ```text
  📍 Москва
  📅 12 августа 2026

  Погода: ливневый дождь
  Температура: +13.3…+17.9 °C
  Утром: +15.6 °C
  Днём: +17.3 °C

  Осадки: до 53%, наиболее вероятно около 08:00
  За сутки: 1.8 мм

  Ветер: до 15.1 км/ч
  Порывы: до 47.2 км/ч

  Магнитная активность: Kp до 2 в ближайшие 24 ч

  Сводка сформирована: 12.08.2026 06:16
  ```

- SHA-256 реальной SQLite `~/.local/share/weather-alert-bot/settings.sqlite3` до и после real preview byte-for-byte совпала: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`.
- Base daily summary preview подтверждён реальными Open-Meteo + NOAA данными. `/today`, Telegram `sendMessage` для этой сводки, постоянный polling, climate norms, risk/warning logic, температурные пользовательские пороги, G1–G5 magnetic business logic, NOAA watches/warnings/alerts, scheduler, scheduled sending и systemd ещё не реализованы.

Следующий архитектурный этап должен быть отдельно выбран техническим лидом.

## Актуальная запись после успешно завершённого controlled real Telegram `/today`

- `src/weather_alert_bot/today_handler.py` — one-shot `/today` реально принял новую private-команду сохранённого владельца, выполнил weather и NOAA запросы, использовал существующие builder/formatter, отправил одну сводку через `sendMessage` и завершился штатно.
- Реальный Linux CLI transcript:

  ```text
  Ожидание новой команды /today...
  Команда /today получена.
  Сводка /today отправлена.
  ```

- Реальный Telegram summary:

  ```text
  Москва
  📅 12 августа 2026

  Погода: ливневый дождь
  Температура: +13.3…+17.9 °C
  Утром: +15.6 °C
  Днём: +17.3 °C

  Осадки: до 55%, наиболее вероятно около 13:00
  За сутки: 1.8 мм

  Ветер: до 15.1 км/ч
  Порывы: до 47.2 км/ч

  Магнитная активность: Kp до 2 в ближайшие 24 ч

  Сводка сформирована: 12.08.2026 06:38
  ```

- До controlled real-test было 315 успешных автоматических тестов. Настоящий `/today` принят от сохранённого владельца, новая private-команда обработана, процесс завершился после одной команды.
- SHA-256 реальной SQLite до и после byte-for-byte совпала: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`; production one-shot остался read-only.
- Weather values, включая precipitation `до 55%, наиболее вероятно около 13:00`, не считаются постоянными: более ранний отдельный real preview дал `до 53%, наиболее вероятно около 08:00`. Это разные запросы в разное время, не ошибка реализации.
- Реальные negative scenarios другого chat ID/group/onboarding error этим запуском не проверялись; они подтверждены автоматическими тестами. Постоянный production polling loop не реализован.

One-shot `/today` теперь подтверждён real Telegram + Open-Meteo + NOAA test. Следующий архитектурный этап выбирается отдельно техническим лидом.

## Base current-day risk assessment: real-test завершён

`src/weather_alert_bot/risk_assessment.py` — pure/deterministic слой оценки текущего локального дня; `--preview-current-risks` — read-only diagnostic CLI. Поддерживаются шесть категорий: magnetic storm, ice, heavy rain, thunderstorm, strong wind и storm. Heat/cold намеренно отложены до climate normals 1991–2020; detection не зависит от пользовательских notification category toggles.

Controlled real preview 12.08.2026 использовал настоящие Open-Meteo и NOAA SWPC data layers и завершился выводом:

```text
Дата: 12.08.2026

Риски по подключённым категориям:
значимых не выявлено.

Не оцениваются на этом этапе: жара, холод
```

SHA-256 production SQLite до и после совпала: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`; preview не изменил SQLite. Реальные positive hazard cases не проверялись; positive/threshold cases подтверждены автоматическими тестами. Полный набор до real-test: **355 тестов успешно**.

`/today` не интегрирован с risk assessment. Event storage/lifecycle/dedup, NOAA watches/warnings/alerts, scheduler, scheduled sending и systemd ещё отсутствуют. Следующий архитектурный этап отдельно выбирает технический лидер.

## Актуальная запись: base climate normals layer после controlled real-test

- `src/weather_alert_bot/climate_normals.py` — отдельный immutable HTTP/parsing и pure calculation layer для Open-Meteo Historical Weather API, baseline `1991-01-01`—`2020-12-31`, fixed `ERA5-Land`, Celsius и daily min/max. Calculation требует полный date range, строит exact calendar-day arithmetic means, хранит sample counts и обрабатывает 29 февраля отдельно; smoothing отсутствует.
- `src/weather_alert_bot/app.py` — добавлен взаимоисключающий read-only diagnostic `--preview-climate-normal`, использующий сохранённые coordinates/timezone, explicit aware UTC current time и ровно один historical request; forecast, NOAA, Telegram и storage writes не вызываются.
- `tests/test_climate_normals.py` и `tests/test_climate_normals_cli.py` — fake HTTP/parsing validation, endpoint/query, safe errors, completeness, means, ordering, leap-day, lookup, deviation, formatter, read-only SQLite и CLI wiring.
- Полный автоматический набор: **372 теста успешно**.
- Controlled real `PYTHONPATH=src python3 -m weather_alert_bot --preview-climate-normal` успешно выполнен для 12 августа на сохранённых latitude/longitude/timezone: Open-Meteo Historical Weather API, полный historical period `1991-01-01`—`2020-12-31`, fixed ERA5-Land, normal min `+13.8 °C`, normal max `+22.1 °C`, `sample_count=30`.
- Перед и после real-test production SQLite имела один и тот же SHA-256: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`; diagnostic подтверждён как read-only. Forecast, NOAA и Telegram API в этом запуске не использовались.
- Persistence/cache climate data, climate SQLite/JSON, heat/cold detector и `±7 °C` threshold не добавлялись. `risk_assessment.py` по-прежнему считает heat/cold unsupported; `/today` не изменён. Leap-day cases подтверждены автоматическими тестами, но отдельный real-test 29 февраля не выполнялся. `technical_spec.md` не изменён; `next_steps.md` отсутствует.

Следующий архитектурный этап отдельно выбирает технический лидер.

## Актуальная связка climate normals → current-day risks

- `climate_normals.py` остаётся владельцем Historical Weather API, расчёта exact calendar-day normals 1991–2020 и lookup `ClimateNormalDay`; historical calculation не выполняется внутри detector.
- `risk_assessment.py` принимает optional `ClimateNormalDay` в конце `assess_current_day_risks(...)`, валидирует тип, дату, finite min/max и положительный integer `sample_count`, затем независимо оценивает `heat` и `cold` по `RiskAssessmentPolicy.heat_deviation_c` / `cold_deviation_c` (default `7.0 °C`).
- `app.py::_preview_current_risks()` — временная diagnostic orchestration: read-only SQLite → один explicit aware UTC `current_time` → weather → NOAA Kp → historical → calculation → local-date lookup → risk assessment. Telegram token/client и `/today` не используются.
- `format_current_day_risk_assessment()` формирует unsupported note из result model; при полном наборе категорий note отсутствует.
- Current-day detector теперь поддерживает все восемь категорий при наличии climate normal, но `/today`, daily summary, scheduler, cache/persistence и notification layer к нему не подключены.

Следующий stop-point: controlled real `--preview-current-risks`; historical request на каждый diagnostic запуск пока допустим только как validation path. `technical_spec.md` не изменять; `next_steps.md` не создавать.

## Актуальная запись: all-eight current-day risk assessment после controlled real-test

- `src/weather_alert_bot/risk_assessment.py` — existing pure detector теперь поддерживает `magnetic_storm`, `heat`, `cold`, `ice`, `heavy_rain`, `thunderstorm`, `strong_wind`, `storm` при наличии валидного `ClimateNormalDay`; automatic heat/cold deviation thresholds по умолчанию `7.0 °C`, inclusive.
- Без climate normal сохраняется backward-compatible six-category mode с `unsupported_categories = ("heat", "cold")`; при climate normal `unsupported_categories = ()`.
- `src/weather_alert_bot/app.py::_preview_current_risks()` — read-only diagnostic chain weather → NOAA → historical → calculation → current-local-date lookup → detector; historical request на ручной запуск пока является временным validation-path ограничением.
- Controlled real `--preview-current-risks` от 13.08.2026 использовал все три внешних data layers и ERA5-Land; вывод: `значимых не выявлено`, без unsupported line. Это подтверждает all-eight mode, но не positive hazard case.
- Production SQLite SHA-256 до/после: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`; byte-for-byte unchanged.
- Full suite: **386 tests OK**. Telegram, `/today`, scheduler, event lifecycle, notification delivery и NOAA watches/warnings/alerts к detector не подключены.

Следующий архитектурный этап отдельно выбирается техническим лидером: сначала спроектировать climate cache/persistence для production path, затем отдельно рассматривать `/today` integration. `technical_spec.md` не менять; `next_steps.md` не создавать.
## Climate cache layer — этап закрыт

- `src/weather_alert_bot/climate_cache.py` — отдельное SQLite-хранилище calculated ClimateNormals 1991–2020. Таблицы `climate_normal_sets` и `climate_normal_days` хранят metadata/set identity и полный snapshot из 366 calendar days, включая 29 February; raw historical data и `user_settings` не используются.
- `SQLiteClimateNormalsCache` — writable schema, read-only открытие, strict validation, corruption errors, atomic snapshot replacement/overwrite, multiple location identities, explicit refresh и versioned cache format/schema.
- `CachedClimateNormals` — immutable wrapper с normals и generated/model/source/schema metadata; `get_or_create_climate_normals()` реализует hit/miss orchestration, `refresh_climate_normals()` — unconditional refresh.
- `src/weather_alert_bot/config.py` — независимые `Settings.climate_db_path` и `WEATHER_ALERT_BOT_CLIMATE_DB_PATH`; `db_path` остаётся только settings DB.
- `src/weather_alert_bot/app.py` — cache-aware `--preview-current-risks` и `--refresh-climate-cache`. Refresh читает saved settings, не требует Telegram token и использует только Historical/calculation/cache. `--preview-climate-normal` остаётся direct source diagnostic.
- `tests/test_climate_cache.py` и `tests/test_climate_cache_cli.py` — temporary SQLite, fake Historical/weather/NOAA clients, validation, atomicity, read-only, miss/hit, refresh и mutual exclusion; full suite после implementation: **405 tests OK**.
- Controlled real validation 13.08.2026: initial `CLIMATE_CACHE_ABSENT`, первый `--preview-current-risks` создал set/day counts `1/366`; повторный запуск с Historical-only DNS guard дал `HISTORICAL_DNS_ATTEMPTS=0`. Production settings SHA-256 до/после неизменен: `dd249d550da41f27c6d2081b8012eff7593964fb355425c4539e9a23fd077424`.
- `/today` пока не подключён к risk assessment/cache; TTL отсутствует. `technical_spec.md` не изменён, `next_steps.md` отсутствует.
