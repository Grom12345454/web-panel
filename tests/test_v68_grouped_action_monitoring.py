from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding='utf-8')

def test_staff_taxonomy_has_exactly_five_business_areas():
    source = read('backend/app/web_app.py')
    labels = source[source.index('USER_ACTIVITY_SECTION_LABELS = {'):source.index('def _registered_user_activity_base_query():')]
    for label in ('Администрирование', 'Аналитика', 'Студенты и участники', 'Работа совета', 'Рабочий стол'):
        assert label in labels
    assert "'other':" not in labels and "'auth':" not in labels and "'events':" not in labels

def test_staff_table_has_no_request_or_result_and_shows_subcategory():
    template = read('frontend/templates/activity/user_activity.html')
    assert '<th>Раздел</th>' in template
    assert '<th>Запрос</th>' not in template
    assert '<th>Результат</th>' not in template
    assert 'row.subcategory_label' in template
    assert 'row.path' not in template and 'row.request_id' not in template

def test_bot_ledger_is_business_event_based_and_grouped():
    template = read('frontend/templates/system/messenger_monitoring.html')
    route = read('backend/app/web_app.py')
    start = route.index('@admin_bp.get("/messenger-monitoring")')
    end = route.index('@admin_bp.get("/messenger-monitoring/student-events.csv")', start)
    handler = route[start:end]
    assert '_collect_registered_bot_activities(request.args)' in handler
    assert 'bot_events' not in handler and 'BotJournalEvent' not in handler
    assert 'event_group_label' in route and 'activity.events' in template
    assert 'Нажатия кнопок и отдельные входящие сообщения не считаются самостоятельными операциями' in template
    assert 'Сообщение</th>' not in template and 'Канал</th>' not in template
    for group in ('Регистрация', 'Заявления', 'Квоты и мероприятия', 'Отказы и отмены'):
        assert group in template

def test_bot_csv_exports_the_same_business_categories_not_transport_results():
    source = read('backend/app/web_app.py')
    start = source.index('def messenger_monitoring_student_events_export(')
    end = source.index('@admin_bp.get("/messenger-monitoring/bot-events.csv")', start)
    export = source[start:end]
    assert 'Раздел действий' in export and 'Что произошло' in export
    assert "row['event_group_label']" in export and "row['action_label']" in export
    assert "'Результат'" not in export and "row['result']" not in export
