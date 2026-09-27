# University Control Pro v2.3

Профессиональная панель управления студенческими направлениями с Telegram-ботом, раздельным хранением данных и расписанием занятий.

## Новая архитектура базы данных

Вместо одной `university.db` проект использует отдельные SQLite-файлы:

- `data/people.sqlite3` — пользователи панели, студенты, направления, заявки, вопросы анкет и руководство.
- `data/events.sqlite3` — мероприятия, квоты, даты и записи на даты.
- `data/lessons.sqlite3` — занятия по направлениям и расписание.
- `data/stats.sqlite3` — агрегированная посещаемость студентов.
- `data/system.sqlite3` — шаблоны уведомлений.

Связи между базами, где SQLite не поддерживает внешние ключи, хранятся как ID и обрабатываются приложением. Это позволяет разделить нагрузку по функциональным зонам, не создавая хрупких cross-database FK.

### Миграция существующей базы

При первом запуске новой версии приложение ищет старую `university.db`, создаёт пять новых БД и переносит существующие таблицы по зонам. Старую базу приложение не удаляет. После успешной миграции создаётся маркер `data/.split_migration_v23`.

Путь к старой БД можно задать через `LEGACY_DATABASE_PATH`, а каталог новых БД — через `DATABASE_DIR`.

## Занятия направления

В каждом направлении появился отдельный раздел `Занятия`. Для занятия можно указать:

- название;
- дату и время начала;
- продолжительность;
- руководителя / преподавателя;
- аудиторию или место;
- вместимость, где `0` означает отсутствие лимита;
- описание;
- статус: запланировано, завершено, отменено.

Доступ:
`Направления → нужное направление → Занятия`.

## Telegram

Пользовательский интерфейс бота остаётся карточным: основные действия доступны через inline-кнопки. Команды не используются как основная навигация. Первая заявка по-прежнему доступна только в Студсовет.

## Запуск

1. Создайте виртуальное окружение.
2. Установите зависимости: `pip install -r requirements.txt`.
3. Скопируйте `.env.example` в `.env`.
4. Заполните `BOT_TOKEN` и `SECRET_KEY`. `BOT_TOKEN` должен быть полным токеном Telegram от `@BotFather`, например `123456789:AA...`; не вставляйте в значение сам текст `BOT_TOKEN=` и не оставляйте кавычки.
5. Запустите `python run.py`.

Веб-панель: `http://127.0.0.1:5000/auth/login` по умолчанию.

Стандартный первоначальный вход панели: `admin@uni.local` / `admin123`.

## Управление студентами и чатами
В веб-панели раздел «Студенты» поддерживает ручное добавление, редактирование и безопасное удаление. В карточке каждого направления есть управление Telegram-чатами: можно подключить несколько чатов, отправить тест, удалить подключение. Новые занятия автоматически публикуются в чаты направления, а новые мероприятия — во все чаты выбранных направлений.


## Telegram-чаты направлений
Не вводите username самого бота в поле Chat ID. Нужен username группы/канала (`@group_name`) или числовой Chat ID (`-100...`). Для приватных чатов без username новый бот автоматически обнаружит чат после добавления в него; затем откройте направление в веб-панели и нажмите «Подключить и проверить». Боты-администраторы получают сообщения из групп, поэтому для уже добавленного бота достаточно отправить обычное сообщение в группе.

## Telegram automation

- When a direction application is approved, the panel creates a join-request invite link for every active Telegram chat of that direction and sends the links to the student's Telegram account.
- The bot automatically approves a join request only when the requesting Telegram account belongs to a student whose direction status is `approved` or `active`.
- When a student is rejected or removed from a direction, the panel removes the student from all active Telegram chats of that direction (when the bot has sufficient administrator rights).
- A quota assigned to the Student Council is always published to every active Student Council chat, regardless of individual chat checkbox selection.
- Other quota directions can target selected chats.
