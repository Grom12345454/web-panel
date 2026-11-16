from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_theme_editor_preview_is_visible_and_updates_real_site_palette():
    template = read('frontend/templates/system/student_app_design.html')
    css = read('frontend/assets/styles/portal/student-app-theme-designer.css')
    js = read('frontend/assets/scripts/portal/student-app-theme-designer.js')
    builder = read('scripts/build_assets.py')
    assert 'id="theme-live-preview"' in template
    assert '.theme-preview-panel {' in css and 'display:none !important' not in css
    # The theme editor explicitly loads its legacy standalone assets for older deployments.
    assert 'css/student-app-theme-designer.css' in template
    assert 'js/student-app-theme-designer.js' in template
    assert 'portal/student-app-theme-designer.css' in read('scripts/build_assets.py')
    assert 'portal/student-app-theme-designer.js' in read('scripts/build_assets.py')
    assert 'portal/student-app-theme-designer.css' in builder
    assert 'portal/student-app-theme-designer.js' in builder
    assert "'--theme-live-accent'" in js
    assert "'--theme-live-secondary'" in js
    assert "document.body.classList.add('theme-live-selection')" in js


def test_student_app_theme_is_applied_during_live_sync_without_reload():
    js = read('frontend/assets/scripts/student/student_app.js')
    assert "document.body.dataset.season=signal.season" in js
    assert "document.body.style.setProperty(`--${name}`,value)" in js
    assert "api('/student-app/api/sync-state')" in js
    assert "api('/student-app/api/me')" in js
    assert 'const STUDENT_SYNC_INTERVAL=5000' in js
    assert 'scheduleStudentSync(0)' in js
    assert 'document.visibilityState===\'hidden\'' in js
    assert 'window.setInterval(syncStudentApp, 8000)' not in js
    assert "if(signal.build&&signal.build!==document.body.dataset.build)" in js
    assert 'preserveStudentView()' in js and 'window.location.reload()' in js


def test_theme_motion_layer_is_built_into_site_and_student_app():
    builder = read('scripts/build_assets.py')
    motion = read('frontend/assets/styles/shared/theme-change-motion-2026.css')
    assert builder.count("'shared/theme-change-motion-2026.css'") == 2
    for theme in ('spring', 'summer', 'autumn', 'winter', 'cosmonautics_day', 'new_year'):
        assert f'data-season="{theme}"' in motion
    assert 'prefers-reduced-motion: reduce' in motion
    assert 'theme-changing' in motion


def test_web_theme_rgb_variables_come_from_the_saved_palette():
    web_app = read('backend/app/web_app.py')
    base = read('frontend/templates/shared/base.html')
    assert '_hex_rgb_triplet(palette[0])' in web_app
    assert '_hex_rgb_triplet(palette[1])' in web_app
    assert '--office-accent-rgb:{{ active_visual_theme_accent_rgb' in base
    assert '--office-secondary-rgb:{{ active_visual_theme_secondary_rgb' in base


def test_v23_student_app_sync_is_faster_and_theme_is_applied_during_form_editing():
    js = read('frontend/assets/scripts/student/student_app.js')
    assert 'const STUDENT_SYNC_INTERVAL=5000' in js
    assert 'scheduleStudentSync(0)' in js
    assert 'document.visibilityState===\'hidden\'' in js
    assert 'window.setInterval(syncStudentApp, 8000)' not in js
    assert 'const revisionChanged=studentSyncRevision!==signal.revision' in js
    assert "Visual settings are safe to apply even while a form is open" in js
    assert 'if(!canApplyStudentUpdate()||noticeModalId!==null)return' in js


def test_v26_bridge_uses_css_only_scene_and_theme_spectrum_is_bundled_twice():
    template = read('frontend/templates/dashboard/overview.html')
    student_app = read('frontend/templates/student/student_app.html')
    builder = read('scripts/build_assets.py')
    spectrum = read('frontend/assets/styles/shared/theme-spectrum-v23.css')
    assert 'hero-energy-core' in template
    assert 'student-aurora-cloud' in student_app
    assert 'data-immersive-model' not in template + student_app
    assert '.glb' not in template + student_app
    assert builder.count("'shared/theme-spectrum-v23.css'") == 2
    assert 'data-theme="cosmonautics_day"' in spectrum
    assert 'prefers-reduced-motion:reduce' in spectrum
