"""Regression tests: employee accounts do not have a username identity."""
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def _user_model_source():
    source = (ROOT / 'backend/app/database/core.py').read_text('utf8')
    return source.split('class User(db.Model):', 1)[1].split('\nclass ', 1)[0]


def test_compact_employee_list_and_accessible_modal():
    html = (ROOT / 'frontend/templates/staff/accounts.html').read_text('utf8')
    assert 'id="staff-editor"' in html
    assert '<dialog' in html
    assert 'id="staff-search"' in html
    assert 'data-staff-id=' in html
    assert 'class="staff-matrix"' not in html
    assert 'data-direction-preset="view"' in html
    assert 'data-direction-preset="manage"' in html
    assert 'id="staff-form-error"' in html


def test_employee_account_form_has_no_username_fields_or_copy():
    html = (ROOT / 'frontend/templates/staff/accounts.html').read_text('utf8')
    assert 'name="telegram_username"' not in html
    assert 'id="staff-username"' not in html
    assert 'username' not in html.lower()
    assert 'Логин для входа' in html
    assert 'Временный пароль' in html
    assert 'name="tg_id"' not in html


def test_employee_model_and_provisioning_have_no_username_attribute():
    model = _user_model_source()
    staff = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf8')
    assert 'telegram_username' not in model
    assert 'telegram_username' not in staff
    assert 'match_handle' not in staff
    assert 'user.tg_id = int(tg_id) if tg_id else None' in staff
    assert 'user.email, user.full_name, user.position, user.phone' in staff


def test_employee_username_column_is_removed_from_existing_database():
    migration = (ROOT / 'backend/app/database/helpers.py').read_text('utf8')
    assert "drop_column_if_exists(settings.PEOPLE_DATABASE_PATH, 'users', 'telegram_username'" in migration
    assert "indexes=('ix_users_telegram_handle',)" in migration
    assert "('telegram_username', 'VARCHAR(32)')" not in migration
    assert 'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_handle' not in migration


def test_private_bot_start_updates_student_profile_but_never_binds_employee_by_username():
    bot = (ROOT / 'backend/app/bot.py').read_text('utf8')
    assert 'Student.query.filter_by(tg_id=user_id).first()' in bot
    assert 'student.telegram_username = username' in bot
    assert 'User.telegram_username' not in bot
    assert 'UserRole' not in bot
    assert 'candidate.tg_id = user_id' not in bot


def test_unbound_panel_accounts_can_sign_in_without_telegram():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf8')
    login = source[source.index('@auth_bp.route("/login"'):source.index("@auth_bp.route('/verify'")]
    assert 'if not user.tg_id or int(user.tg_id) <= 0 or not settings.BOT_TOKEN:' in login
    assert 'UserRole.SUPER_ADMIN.value' in login
    assert 'user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value}' in login
    assert "session['user_id'] = user.id" in login
    assert "redirect(url_for('auth.verify_otp'), code=303)" in login
    template = (ROOT / 'frontend/templates/auth/login.html').read_text('utf8')
    assert 'Сотрудники без Telegram-привязки входят по логину и паролю' in template


def test_template_parses_with_jinja():
    template = (ROOT / 'frontend/templates/staff/accounts.html').read_text('utf8')
    assert Environment().parse(template) is not None
