"""Cosmic user interface: no status stepper, accessible motion and generated bundles."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT=Path(__file__).resolve().parents[1]

def read(path): return (ROOT/path).read_text(encoding='utf8')

def test_application_steps_removed_but_status_and_actions_remain():
    app=read('frontend/assets/scripts/student/student_app.js')
    assert 'applicationProgress(' not in app
    assert 'mission-app-progress' not in app
    assert 'statusText(d.status)' in app
    assert 'data-action="remove-app"' in app
    assert 'd.rejection_reason' in app

def test_both_templates_have_single_accessible_cosmos_scene():
    for name in ('frontend/templates/student/student_app.html','frontend/templates/shared/base.html'):
        content=read(name)
        assert content.count('class="cosmos-field" aria-hidden="true"')==1
        assert 'cosmos-field__nebula' in content
        assert 'cosmos-field__stars--distant' in content
        assert 'cosmos-field__stars--near' in content

def test_shared_cosmos_styles_and_script_are_built_once_per_bundle():
    for name in ('static/css/site.bundle.css','static/css/student-app.bundle.css'):
        assert read(name).count('BEGIN frontend/assets/styles/shared/cosmos-world-2026.css')==1
    for name in ('static/js/site.bundle.js','static/js/student-app.bundle.js'):
        assert read(name).count('BEGIN frontend/assets/scripts/shared/cosmos-world-2026.js')==1

def test_effect_has_motion_safety_and_doesnt_interrupt_controls():
    css=read('frontend/assets/styles/shared/cosmos-world-2026.css')
    js=read('frontend/assets/scripts/shared/cosmos-world-2026.js')
    for token in ('prefers-reduced-motion:reduce','pointer:coarse','pointer-events: none','forced-colors:active'):
        assert token in css
    assert 'visibilitychange' in js
    assert 'cosmos-paused' in js
    for obsolete in ('requestAnimationFrame(', 'pointermove', 'getBoundingClientRect(',
                     '--cosmos-tilt-x', '--cosmos-tilt-y'):
        assert obsolete not in js
    for banned in ('setInterval(', 'location.reload(', 'localStorage', 'fetch('):
        assert banned not in js

def test_jinja_pages_compile():
    env=Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(path.relative_to(ROOT / 'frontend/templates').as_posix())
