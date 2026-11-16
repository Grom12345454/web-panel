from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_telegram_color_methods_are_guarded_by_bot_api_versions():
    for path in (
        'frontend/assets/scripts/student/student_app.js',
        'frontend/assets/standalone/js/student_app.js',
        'static/js/student-app.bundle.js',
        'static/js/student_app.js',
    ):
        source = read(path)
        assert "telegramSupportsBotApi('6.1')" in source
        assert "telegramSupportsBotApi('6.9')?'#061321':'bg_color'" in source
        assert "if(!telegramSupportsBotApi('6.1'))return" in source


def test_theme_updates_are_broadcast_locally_and_reconciled_quickly():
    editor = read('frontend/assets/scripts/portal/student-app-theme-designer.js')
    site = read('frontend/assets/scripts/portal/theme-live-sync.js')
    student = read('frontend/assets/scripts/student/student_app.js')
    server = read('backend/app/web_app.py')
    assert "new BroadcastChannel('student-council-theme-v60')" in editor
    assert "new BroadcastChannel('student-council-theme-v60')" in site
    assert "new BroadcastChannel('student-council-theme-v60')" in student
    designer_template = read('frontend/templates/system/student_app_design.html')
    assert 'data-theme-css-vars=' in designer_template
    assert 'message.themeVars' in student and 'themeVars:' in editor
    assert 'const POLL_INTERVAL = 5000' in site
    assert 'const STUDENT_SYNC_INTERVAL=5000' in student
    assert '"asset_version"]("js/site.bundle.js")' in server


def test_new_asset_fingerprints_reload_when_screen_is_safe():
    base = read('frontend/templates/shared/base.html')
    site = read('frontend/assets/scripts/portal/theme-live-sync.js')
    student = read('frontend/assets/scripts/student/student_app.js')
    assert 'data-build="{{ asset_version(\'js/site.bundle.js\') }}:{{ asset_version(\'css/site.bundle.css\') }}"' in base
    assert 'window.location.reload()' in site
    assert 'preserveStudentView();' in student
    assert 'window.location.reload();' in student
    assert 'canApplyStudentUpdate()' in student


def test_approval_and_activation_send_native_personal_cabinet_entry():
    applications = read('backend/app/services/applications.py')
    web = read('backend/app/web_app.py')
    assert "'web_app':{'url':app_url}" in applications
    assert "'text':'Открыть личный кабинет'" in applications
    assert 'notify_approval(student, direction, send_invites=True, immediately_active=True)' in web
    assert "launch_url = vk_app_url() if link.platform == 'vk' else max_app_url()" in applications


def test_student_app_returns_to_dashboard_after_a_new_activation():
    source = read('frontend/assets/scripts/student/student_app.js')
    assert "['active','approved'].includes(String(item.status||''))" in source
    assert "['pending','interview'].includes(oldStatuses.get(Number(item.id))||'')" in source
    assert "activeTab='home';registrationStarted=false;" in source
    assert 'Заявка принята и активирована' in source


def test_stronger_theme_smoke_is_shared_and_keeps_performance_reductions():
    manifest = read('scripts/build_assets.py')
    smoke = read('frontend/assets/styles/shared/theme-smoke-v60.css')
    assert "'shared/theme-smoke-v60.css'" in manifest
    assert 'theme-smoke-white-v60' in smoke
    assert 'theme-smoke-blue-v60' in smoke
    assert 'theme-smoke-red-v60' in smoke
    assert 'prefers-reduced-motion: reduce' in smoke
    assert 'body.student-app-body[data-season]' in smoke and '--theme-smoke-primary' in smoke
    assert 'perf-economy' in read('frontend/assets/styles/shared/performance-budget-2026.css')


def test_legacy_holiday_stylesheet_has_no_bare_text_selector():
    css = read('frontend/assets/styles/shared/holiday-atmosphere-v52.css')
    assert '/* Unified atmosphere:' in css and 'Seasonal glyph/leaf/snow/ember/orbit particle variants are intentionally disabled. */\n.holiday-particle' in css
