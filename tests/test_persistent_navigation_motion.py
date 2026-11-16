"""Regression coverage for persistent admin navigation and Student App tab rendering."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_shell_does_not_replay_entry_animation_on_each_route():
    page_motion = read("frontend/assets/scripts/shared/page-entry-motion.js")
    professional_css = read("frontend/assets/styles/shared/professional-experience-2026.css")
    assert "const shell = document.querySelector('.app-shell')" not in page_motion
    assert "body.uc-body:not(.is-login-page) .app-shell,body.uc-body:not(.is-login-page) .sidebar{animation:none!important" in professional_css
    assert "@media(prefers-reduced-motion:reduce)" in professional_css


def test_student_app_preserves_shell_and_changes_only_tab_content():
    js = read("frontend/assets/scripts/student/student_app.js")
    assert "if(!previousMain){" in js
    assert "main.innerHTML=content;" in js
    assert "app.innerHTML=shell()+`<main class=\"student-main\"" in js
    assert "function updateStudentNav()" in js
    assert "render({motion:false})" in js


def test_bot_webapp_sdks_and_signed_headers_are_preserved():
    template = read("frontend/templates/student/student_app.html")
    js = read("frontend/assets/scripts/student/student_app.js")
    assert "telegram.org/js/telegram-web-app.js" in template
    assert "st.max.ru/js/max-web-app.js" in template
    assert "X-Telegram-Init-Data" in js
    assert "X-Max-Init-Data" in js
    assert "X-VK-Launch-Params" in js


def test_interaction_motion_respects_reduced_motion():
    admin_css = read("frontend/assets/styles/shared/professional-experience-2026.css")
    student_css = read("frontend/assets/styles/student/student-responsive-2026.css")
    app_js = read("frontend/assets/scripts/portal/app.js")
    assert "prefers-reduced-motion" in admin_css
    assert "@media (prefers-reduced-motion: reduce)" in student_css
    assert "reduceMotionQuery?.matches" in app_js
