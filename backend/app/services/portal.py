"""Shared portal metadata used by the web panel, Telegram bot and Mini App.

The important part is that labels and capabilities live in one place. The bot,
admin UI and Mini App still use the same database/services for all mutations.
"""

BOT_COMMANDS = [
    ("start", "Начало работы", "Проверка профиля и запуск регистрации"),
    ("apply", "Подать заявление", "Выбор любого доступного направления; повторная заявка в выбранное направление недоступна"),
    ("status", "Мои заявления", "Статус рассмотрения отдельно по каждому направлению"),
    ("events", "Мероприятия", "Доступные мероприятия для активных направлений"),
    ("profile", "Профиль", "Данные студента"),
    ("help", "Справочная информация", "Порядок работы с сервисом"),
    ("leadership", "Управление студентами", "Только назначенному руководству"),
]

def command_map():
    return {code: {"title": title, "description": description} for code, title, description in BOT_COMMANDS}
