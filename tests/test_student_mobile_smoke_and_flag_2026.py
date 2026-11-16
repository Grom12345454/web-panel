from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_student_app_smoke_is_larger_layered_transparent_and_pointer_safe():
    source = read('frontend/assets/styles/shared/holiday-atmosphere-v52.css')
    bundle = read('static/css/student-app.bundle.css')
    for css in (source, bundle):
        assert 'width: min(82vw, 1040px)' in css
        assert '.holiday-smoke::before' in css
        assert '@keyframes holiday-smoke-wisp' in css
        assert 'mix-blend-mode: screen' in css
        assert 'pointer-events: none' in css
        assert 'prefers-reduced-motion: reduce' in css


def test_student_app_responsive_profiles_use_capabilities_and_safe_areas():
    css = read('frontend/assets/styles/student/student-responsive-2026.css')
    bundle = read('static/css/student-app.bundle.css')
    js = read('frontend/assets/scripts/student/student_app.js')
    template = read('frontend/templates/student/student_app.html')
    for content in (css, bundle):
        assert 'safe-area-inset-top' in content
        assert 'safe-area-inset-bottom' in content
        assert 'pointer: coarse' in content
        assert 'horizontal-viewport-segments' in content
        assert 'student-visual-viewport-height' in content
    assert "window.visualViewport" in js
    assert "body.dataset.runtime=runtime" in js
    assert "body.dataset.deviceFamily" in js
    assert 'interactive-widget=resizes-content' in template


def test_russian_flag_is_removed_from_topic_labels_but_graphic_tricolour_remains():
    js = read('frontend/assets/scripts/student/student_app.js')
    holiday_css = read('frontend/assets/styles/shared/holiday-atmosphere-v52.css')
    bundle_js = read('static/js/student-app.bundle.js')
    bundle_css = read('static/css/student-app.bundle.css')
    assert 'function withoutRussianFlag(value)' in js
    assert 'withoutRussianFlag(d.name)' in js
    assert 'topicIcon(d.icon)' in js
    assert 'withoutRussianFlag(d.name)' in bundle_js
    assert '.holiday-flag' not in holiday_css and '.holiday-flag' not in bundle_css
    assert 'rgba(255,255,255,.64)' in holiday_css
    assert 'rgba(0,57,166,.72)' in holiday_css
    assert 'rgba(213,43,30,.62)' in holiday_css


def test_theme_cards_have_no_flag_graphic_and_keep_tricolour_smoke():
    source = read('backend/app/web_app.py')
    template = read('frontend/templates/system/student_app_design.html')
    flag_emoji = chr(0x1F1F7) + chr(0x1F1FA)
    assert flag_emoji not in source
    assert 'theme.emoji' in template
    assert 'holiday-flag' not in read('frontend/templates/student/student_app.html')
    assert 'holiday-flag' not in read('frontend/templates/shared/base.html')


def test_smoke_and_light_ribbon_use_theme_palette_and_reduce_motion():
    css = read('frontend/assets/styles/shared/holiday-atmosphere-v52.css')
    bundle = read('static/css/student-app.bundle.css')
    for content in (css, bundle):
        assert '--smoke-accent-rgb' in content
        assert '--smoke-secondary-rgb' in content
        assert 'theme-light-ribbon' in content
        assert 'student-theme-atmosphere::after' in content
        assert 'prefers-reduced-motion: reduce' in content


def test_responsive_profiles_cover_dynamic_viewport_and_tablet_form_factor():
    css = read('frontend/assets/styles/student/student-responsive-2026.css')
    js = read('frontend/assets/scripts/student/student_app.js')
    assert '100svh' in css and '100dvh' in css
    assert 'student-visual-viewport-width' in js
    assert "body.dataset.formFactor=tablet?'tablet':touch?'handset':'desktop'" in js
    assert "viewport?.addEventListener('scroll'" in js
    assert "body.dataset.viewportProfile" in js
    assert "student-keyboard-open" in js


def test_tricolour_smoke_is_shared_by_all_portal_roles_and_student_app():
    source = read('frontend/assets/styles/shared/holiday-atmosphere-v52.css')
    portal_bundle = read('static/css/site.bundle.css')
    student_bundle = read('static/css/student-app.bundle.css')
    assert 'body.uc-body:is([data-theme="russia_day"]' in source
    assert 'body.uc-body.role-super_admin:is(' not in source
    for content in (portal_bundle, student_bundle):
        assert 'rgba(255,255,255,.64)' in content
        assert 'rgba(0,57,166,.72)' in content
        assert 'rgba(213,43,30,.62)' in content
        assert 'theme-smoke-white-v60' in content


def test_numbered_portal_ui_polish_layers_are_consolidated_in_the_main_bundle():
    manifest = read('scripts/build_assets.py')
    bundle = read('static/css/site.bundle.css')
    assert "'portal/ui-polish.css'" in manifest
    for old_layer in ('portal/ui-polish-v5.css', 'portal/ui-polish-v6.css',
                      'portal/ui-polish-v7.css', 'portal/ui-polish-v8.css',
                      'portal/ui-polish-v9.css'):
        assert old_layer not in manifest
    assert 'Unified portal UI polish layer' in bundle
