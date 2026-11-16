from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(name): return (ROOT/name).read_text(encoding='utf-8')

def test_student_app_polls_for_live_membership_updates_and_applies_theme_without_reload():
    js=read('frontend/assets/scripts/student/student_app.js')
    assert 'const STUDENT_SYNC_INTERVAL=5000' in js
    assert 'scheduleStudentSync(0)' in js
    assert "document.visibilityState==='hidden'" in js
    assert 'window.setInterval(syncStudentApp, 8000)' not in js
    assert "api('/student-app/api/sync-state')" in js
    assert "api('/student-app/api/me')" in js
    assert 'const revisionChanged=studentSyncRevision!==signal.revision' in js
    assert 'Visual settings are safe to apply even while a form is open' in js
    assert "if(signal.build&&signal.build!==document.body.dataset.build)" in js
    assert 'preserveStudentView()' in js and 'window.location.reload()' in js

def test_management_bridge_is_css_only_and_theme_css_is_bundled_for_both_clients():
    template=read('frontend/templates/dashboard/overview.html')
    student=read('frontend/templates/student/student_app.html')
    builder=read('scripts/build_assets.py')
    css=read('frontend/assets/styles/shared/theme-spectrum-v23.css')
    assert 'hero-energy-core' in template and 'student-aurora-cloud' in student
    assert 'data-immersive-model' not in template+student
    assert 'campus-ship.glb' not in template+student
    assert "'shared/theme-spectrum-v23.css'" in builder and builder.count("'shared/theme-spectrum-v23.css'")==2
    assert 'body.uc-body[data-theme="summer"]' in css
    assert 'body.student-app-body[data-season="winter"]' in css
    assert 'prefers-reduced-motion:reduce' in css

def test_all_local_3d_models_and_renderers_are_removed():
    assert not (ROOT/'static/models').exists()
    assert not (ROOT/'frontend/assets/scripts/shared/immersive-3d-2026.js').exists()
    assert not (ROOT/'frontend/assets/standalone/js/student-universe.js').exists()
    assert not list(ROOT.rglob('*.glb'))
    builder=read('scripts/build_assets.py')
    assert 'immersive-3d-2026.js' not in builder
