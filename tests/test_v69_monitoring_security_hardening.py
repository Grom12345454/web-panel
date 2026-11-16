from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def functions(path):
    source = read(path)
    tree = ast.parse(source)
    return source, {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_legacy_activity_route_is_not_an_authenticated_staff_data_dump():
    source, nodes = functions('backend/app/web_app.py')
    node = nodes['activity_log']
    decorators = [ast.unparse(item) for item in node.decorator_list]
    code = ast.get_source_segment(source, node)
    assert 'super_admin_required' in decorators
    assert "redirect(url_for('admin.messenger_monitoring')" in code
    assert 'StudentActivity.query' not in code
    assert 'render_template("activity/list.html"' not in code


def test_registered_bot_timeline_uses_allowlisted_descriptions_and_never_returns_raw_reasons():
    source, nodes = functions('backend/app/web_app.py')
    collector = ast.get_source_segment(source, nodes['_collect_registered_bot_activities'])
    live = ast.get_source_segment(source, nodes['bot_activity_live'])
    assert '_safe_bot_activity_description(item.action)' in collector
    assert "'description': safe_description" in collector
    assert '_safe_bot_activity_description(row.action)' in live
    assert '"description": row.description' not in live
    assert 'StudentActivity.description.ilike(pattern' not in collector


def test_staff_ui_keeps_low_level_diagnostics_hidden_but_exposes_safe_filters():
    template = read('frontend/templates/activity/user_activity.html')
    assert 'name="method"' in template and 'name="level"' in template
    for field in ('row.path', 'row.request_id', 'row.status_code', 'row.ip_address'):
        assert field not in template
    assert '<th>Раздел</th>' in template


def test_bot_transport_journal_stores_allowlisted_summaries_and_csv_is_formula_safe():
    journal = read('backend/app/services/bot_journal.py')
    routes = read('backend/app/services/bot_journal_routes.py')
    assert 'def safe_summary(value):' in journal
    assert 'label = safe_summary(summary)' in journal
    assert "return 'Событие интеграции'" in journal
    assert 'def spreadsheet_safe(value):' in routes
    assert 'writer.writerow(map(spreadsheet_safe' in routes
    assert 'safe_summary(row.summary)' in routes
    assert "safe_error_labels.get(job.last_error" in routes


def test_bot_business_action_csv_is_formula_safe_and_bounded():
    source, nodes = functions('backend/app/web_app.py')
    export = ast.get_source_segment(source, nodes['messenger_monitoring_student_events_export'])
    assert 'safe_cell' in export
    assert 'export_limit=10000' in export


def test_legacy_transport_errors_are_sanitized_when_read_from_the_database():
    source = read('backend/app/web_app.py')
    helper = source[source.index('def _recent_bot_transport_incidents'):source.index('def _messenger_monitoring_snapshot_data')]
    assert 'safe_summary(row.summary)' in helper
    template = read('frontend/templates/system/messenger_monitoring.html')
    assert 'item.safe_summary' in template
    assert 'item.summary' not in template
    legacy_template = read('frontend/templates/activity/bot_journal.html')
    assert 'safe_summary(item.summary)' in legacy_template
    old_activity_template = read('frontend/templates/activity/list.html')
    assert 'item.activity.description' not in old_activity_template

