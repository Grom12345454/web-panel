from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_registration_does_not_swallow_shared_education_choice():
    registration = (ROOT / 'backend/app/handlers/registration.py').read_text(encoding='utf-8')
    assert 'def is_legacy_education_reply(message: types.Message) -> bool:' in registration
    assert "@router.message(F.text.in_({'🏫 Колледж', '🎓 Институт'}), is_legacy_education_reply)" in registration
    assert "state.get('step') == RegState.EDUCATION_TYPE" in registration


def test_shared_registration_keyboard_choice_reaches_multi_messenger_flow():
    menu = (ROOT / 'backend/app/handlers/menu.py').read_text(encoding='utf-8')
    bot_ui = (ROOT / 'backend/app/services/bot_ui.py').read_text(encoding='utf-8')
    shared = (ROOT / 'backend/app/services/multi_messenger.py').read_text(encoding='utf-8')
    assert "elif _get_flow('telegram', user_id):" in menu
    assert "handle_private_text('telegram', user_id, text" in menu
    assert "Action('🏫 Колледж', 'education_college')" in bot_ui
    assert "'education_college': '1'" in bot_ui
    assert "if val in {'1', 'колледж', 'college'}" in shared
