from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def source(path): return (ROOT/path).read_text(encoding='utf-8')

def test_cinematic_css_only_design_layer_is_last_in_both_bundles():
    build=source('scripts/build_assets.py')
    css_name='shared/neural-cinema-v61.css'
    assert build.count(css_name)==2
    for bundle in ('static/css/site.bundle.css','static/css/student-app.bundle.css'):
        text=source(bundle)
        assert text.rfind('BEGIN frontend/assets/styles/'+css_name) >= 0

def test_login_keeps_auth_contract_and_uses_external_design_layer():
    login=source('frontend/templates/auth/login.html')
    assert 'name="csrf_token" value="{{ csrf_token() }}"' in login
    assert 'name="username"' in login and 'name="password"' in login
    assert 'id="password-visibility"' in login
    assert '<style' not in login.lower()

def test_no_3d_model_markup_or_glb_files_remain_in_deployed_app():
    for path in ('frontend/templates/shared/base.html','frontend/templates/dashboard/overview.html','frontend/templates/student/student_app.html','frontend/templates/auth/login.html'):
        text=source(path)
        assert 'data-immersive-model' not in text and '.glb' not in text
    assert not list(ROOT.rglob('*.glb'))
    assert not (ROOT/'frontend/assets/scripts/shared/immersive-3d-2026.js').exists()
