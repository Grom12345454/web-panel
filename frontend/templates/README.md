# Шаблоны — единая структура

| Папка | Назначение |
|---|---|
| `shared/` | Единый базовый шаблон, общая страница ошибки |
| `auth/` | Авторизация сотрудников |
| `dashboard/` | Главная панель |
| `students/` | Список, форма, группы, блокировки, статистика |
| `directions/` | Направления, чаты, вопросы, отчёты |
| `leadership/` | Управление руководителями, публичный каталог |
| `calendar/` | Общий календарь |
| `lessons/` | Занятия |
| `events/` | Мероприятия, участники, анонсы |
| `activity/` | Журнал действий, отчёты, активность ботов |
| `statistics/` | Аналитика |
| `system/` | Уведомления, обслуживание, дизайн |
| `student/` | **Единый Student App для Telegram / VK / MAX** |

Все внутренние страницы наследуют `shared/base.html`, а `student/student_app.html`
— отдельная мобильная оболочка. Дубли шаблонов в корне удалены, `render_template`
использует пути из этой карты. Не добавляйте альтернативные корневые копии.

CSS/JS собираются из ``frontend/assets/` через `python scripts/build_assets.py`.

## Журнал трёх ботов

`activity/bot_journal.html` — оперативная лента Telegram, VK и MAX. Стили: `static/css/bot-journal.css`; автоматическая проверка: `static/js/bot-journal.js`. Существующие страницы `activity/bot_activity*` остаются для истории заявок.

### Объединение расписания V4

Основная страница занятий и мероприятий — `calendar/index.html`. Старые GET-адреса списков перенаправляют сюда. Student App формирует месячную календарную сетку через `frontend/assets/scripts/student/student_app.js` и `frontend/assets/styles/student/unified-calendar-2026.css`. Разделы журнала расположены в `activity/audit_log.html` (веб-действия) и `activity/bot_journal.html` (только Telegram/VK/MAX). Операции очистки — `system/maintenance.html`.
