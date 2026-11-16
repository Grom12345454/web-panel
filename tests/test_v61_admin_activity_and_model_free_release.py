from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_admin_activity_route_is_super_admin_only_and_tracks_registered_web_accounts():
    app = read('backend/app/web_app.py')
    start = app.index("@admin_bp.route('/user-activity')")
    end = app.index('@admin_bp.route("/activity")', start)
    route = app[start:end]
    assert '@super_admin_required' in route
    assert "_registered_user_activity_query(request.args)" in route
    assert 'HttpAuditLog' in route
    assert 'StudentActivity.query' not in route
    assert 'union_all' not in route
    assert 'selected_accounts' in route and 'selected_views' in route and 'selected_changes' in route
    assert 'request bodies' in route and 'tokens' in route
    assert "@admin_bp.get('/user-activity/export.csv')" in route


def test_activity_query_excludes_anonymous_and_domain_events_and_supports_account_filters():
    app = read('backend/app/web_app.py')
    start = app.index('def _registered_user_activity_base_query():')
    end = app.index('def _registered_user_activity_section(row):', start)
    query_helpers = app[start:end]
    assert 'HttpAuditLog.actor_user_id.isnot(None)' in query_helpers
    assert 'HttpAuditLog.actor_role.in_(REGISTERED_WEB_ACCOUNT_ROLES)' in query_helpers
    assert 'User.email.ilike' in query_helpers and 'User.full_name.ilike' in query_helpers
    assert "values['section']" in query_helpers
    assert "HttpAuditLog.status_code >= 400" in query_helpers
    assert "HttpAuditLog.duration_ms >= 1500" in query_helpers
    assert "HttpAuditLog.method == values['method']" in query_helpers
    assert 'StudentActivity' not in query_helpers and 'BotJournalEvent' not in query_helpers


def test_activity_screen_describes_registered_accounts_not_related_students():
    template = read('frontend/templates/activity/user_activity.html')
    for key in ('name="q"', 'name="section"', 'name="role"',
                'name="actor"', 'name="start"', 'name="end"'):
        assert key in template
    assert '<table' in template and '<thead>' in template and '<tbody>' in template
    assert 'row.account_name' in template and 'row.action_label' in template
    assert 'row.path' not in template and 'row.request_id' not in template
    assert 'row.subcategory_label' in template
    assert 'Запрос</th>' not in template and 'Результат</th>' not in template
    assert 'Экспорт CSV' in template
    assert 'связанный студент не всегда является инициатором события' not in template
    assert 'События с участием студентов' not in template
    assert 'Только зарегистрированные аккаунты' in template
    assert 'Содержимое форм' in template


def test_admin_nav_links_activity_page_only_for_super_admin():
    base = read('frontend/templates/shared/base.html')
    assert "url_for('admin.user_activity_log')" in base
    assert "admin.admin_audit_log" in base
    assert "session.user_role == 'super_admin'" in base


def test_no_3d_model_binary_source_generator_or_runtime_reference_remains():
    assert not list(ROOT.rglob('*.glb'))
    assert not list(ROOT.rglob('*.gltf'))
    for name in ('generate_ship_model.py', 'generate_immersive_model.py', 'generate_spaceplane_model.py'):
        assert not (ROOT / 'scripts' / name).exists()
    for name in ('frontend/assets/scripts/shared/immersive-3d-2026.js', 'frontend/assets/standalone/js/student-universe.js'):
        assert not (ROOT / name).exists()
    for path in ('frontend/templates/shared/base.html', 'frontend/templates/dashboard/overview.html', 'frontend/templates/student/student_app.html'):
        text = read(path)
        assert 'data-immersive-model' not in text and '.glb' not in text
