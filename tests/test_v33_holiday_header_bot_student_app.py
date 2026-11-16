from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_russian_holiday_palettes_use_dark_depth_not_ruby_red():
    app = read("backend/app/web_app.py")
    for theme, depth in (("russia_day", "#0D2350"), ("flag_day", "#0D1B36"), ("unity_day", "#111D37")):
        line = next(line for line in app.splitlines() if f'"{theme}": {{"label"' in line)
        assert depth in line
        assert "'#E43E52']" not in line and "'#D94D65']" not in line

def test_staff_topbar_uses_neutral_dark_glass_on_all_theme_choices():
    css = read("frontend/assets/styles/shared/immersive-emotion-v29.css")
    assert "body.uc-body:not(.is-login-page) .topbar" in css
    rule = css.split("body.uc-body:not(.is-login-page) .topbar", 1)[1].split("}", 1)[0]
    assert "rgba(7, 18, 32, .97)" in rule
    assert "var(--v29-depth)" not in rule
    assert "border-bottom-color: rgba(145, 190, 235, .17)" in rule

def test_student_app_is_separate_bot_embedded_panel_in_theme_designer():
    template = read("frontend/templates/system/student_app_design.html")
    student = read("frontend/templates/student/student_app.html")
    assert "внутри ботов Telegram, VK и MAX" in template
    assert "standalone=1" not in template
    assert 'class="student-app-body"' in student
    assert "body.student-app-body[data-season]" in read("frontend/assets/styles/shared/immersive-emotion-v29.css")

def test_built_bundles_contain_fixed_neutral_topbar_rule():
    for path in ("static/css/site.bundle.css", "static/css/student-app.bundle.css"):
        assert "rgba(7, 18, 32, .97)" in read(path)
    assert int(read("PROJECT_VERSION").strip().split(".")[0]) >= 33
