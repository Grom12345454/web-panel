from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_student_app_has_secure_account_link_routes_and_idempotent_registration():
    web = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    assert '"/student-app/api/accounts"' in web
    assert '"/student-app/api/accounts/code"' in web
    assert '"/student-app/api/accounts/<int:request_id>/review"' in web
    assert '"/student-app/api/accounts/<platform>"' in web
    assert 'def student_app_review_link_request' in web
    assert 'current_platform=actor' in web
    assert 'link_allowed' in web
    assert 'already_registered' in web

def test_student_app_account_controls_are_bundled_and_available_in_personal_data():
    js = (ROOT / "frontend/assets/scripts/student/student_app.js").read_text("utf-8")
    bundle = (ROOT / "static/js/student-app.bundle.js").read_text("utf-8")
    for marker in ('Привязанные аккаунты', 'account-generate', 'account-confirm-unlink', 'account-review', 'ОТВЯЗАТЬ', 'my-connected-accounts'):
        assert marker in js
        assert marker in bundle
    # Account actions must be inside the Personal Data/profile disclosure, not only in More.
    profile = js.split('function profile(){', 1)[1].split('function leadershipDirectory(){', 1)[0]
    assert 'accountSettings(true)' in profile
    assert 'Привязать ${meta.label}' in js and 'Привязать ${meta.label}' in bundle
    assert "['home','more'].includes(activeTab)" in js
    assert 'account-links-fix.css' in (ROOT / "scripts/build_assets.py").read_text("utf-8")
