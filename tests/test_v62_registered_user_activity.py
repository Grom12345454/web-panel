from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_registered_user_audit_route_and_export_are_super_admin_only():
    src = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    tree = ast.parse(src)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'user_activity_log' in functions
    assert 'user_activity_export' in functions
    relevant = "\n".join(
        line
        for name in ('user_activity_log', 'user_activity_export', 'user_activity_pdf')
        for line in src.splitlines()[functions[name].lineno - 1:functions[name].end_lineno]
    )
    assert all(
        any(ast.unparse(decorator) == 'super_admin_required'
            for decorator in functions[name].decorator_list)
        for name in ('user_activity_log', 'user_activity_export', 'user_activity_pdf')
    )
    assert "_registered_user_activity_query(request.args)" in relevant
    assert 'StudentActivity.query' not in relevant
    assert 'union_all' not in relevant


def test_registered_user_activity_is_only_authenticated_user_model_accounts():
    src = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    start = src.index('def _registered_user_activity_base_query():')
    end = src.index('def _registered_user_activity_section(row):', start)
    query_code = src[start:end]
    assert 'HttpAuditLog.actor_user_id.isnot(None)' in query_code
    assert 'HttpAuditLog.actor_role.in_(REGISTERED_WEB_ACCOUNT_ROLES)' in query_code
    assert "~HttpAuditLog.path.like('/student-app%')" in query_code
    assert "~HttpAuditLog.action.like('student_app.%')" in query_code
    assert 'User.email.ilike' in query_code
    assert 'User.full_name.ilike' in query_code
    assert "values['section']" in query_code
    assert "HttpAuditLog.method == values['method']" in query_code
    assert "HttpAuditLog.status_code >= 400" in query_code
    assert "HttpAuditLog.duration_ms >= 1500" in query_code
    assert 'StudentActivity' not in query_code
    assert 'BotJournalEvent' not in query_code


def test_user_activity_table_has_real_account_identity_actions_and_filters():
    template = (ROOT / 'frontend/templates/activity/user_activity.html').read_text('utf-8')
    for field in ('q', 'section', 'role', 'method', 'level', 'actor', 'start', 'end'):
        assert f'name="{field}"' in template
    for field in ('row.account_name', 'row.account_login', 'row.actor_user_id', 'row.action_label',
                  'row.section_label', 'row.subcategory_label'):
        assert field in template
    # v68 intentionally removes low-level request diagnostics from the user-facing table.
    for field in ('row.path', 'row.status_code', 'row.request_id', 'row.ip_address'):
        assert field not in template
    assert 'не являются инициаторами' not in template
    assert 'событиях о студентах' not in template.lower()
    assert 'Экспорт CSV' in template


def test_activity_template_compiles_with_the_rest_of_the_site():
    env = Environment(loader=FileSystemLoader(ROOT / 'frontend/templates'))
    for template in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(template.relative_to(ROOT / 'frontend/templates').as_posix())


def test_middleware_records_authenticated_registered_user_requests_but_not_background_polls():
    src = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    assert 'REGISTERED_WEB_ACCOUNT_ROLES = tuple(role.value for role in UserRole)' in src
    assert 'is_registered_account_actor' in src
    assert 'is_student_identity_request' in src
    assert 'Do not attribute an expired/revoked session' in src
    assert 'Resolve the actor from the live account row' in src
    assert 'is_staff_write_request' in src
    assert 'or is_staff_write_request' in src
    assert 'HttpAuditLog.__table__.insert().values(**audit_values)' in src
    assert 'Query strings and request bodies are never stored.' in src
