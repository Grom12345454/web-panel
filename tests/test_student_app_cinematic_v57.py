from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_cinematic_student_layer_is_part_of_public_bundle():
    manifest = read('scripts/build_assets.py')
    source = read('frontend/assets/styles/student/student-app-cinematic-v57.css')
    bundle = read('static/css/student-app.bundle.css')
    assert 'student/student-app-cinematic-v57.css' in manifest
    assert 'V57 · Student App cinematic polish' in source
    assert 'V57 · Student App cinematic polish' in bundle


def test_smoke_has_three_independent_streams_and_six_wisp_animation_tracks():
    source = read('frontend/assets/styles/student/student-app-cinematic-v57.css')
    bundle = read('static/css/student-app.bundle.css')
    for css in (source, bundle):
        for keyframe in (
            'student-smoke-current-a', 'student-smoke-current-b',
            'student-smoke-current-c', 'student-smoke-curl-a',
            'student-smoke-curl-b', 'student-cinema-aurora',
            'student-cinema-light-sweep',
        ):
            assert f'@keyframes {keyframe}' in css
        assert 'pointer-events: none' in css
        assert 'mix-blend-mode: screen' in css
        assert 'prefers-reduced-motion: reduce' in css


def test_student_cinematic_design_is_scoped_and_respects_touch_devices():
    css = read('frontend/assets/styles/student/student-app-cinematic-v57.css')
    assert 'body.student-app-body #app .hero' in css
    assert 'body.student-app-body #app .nav' in css
    assert '@media (hover: hover) and (pointer: fine)' in css
    assert '@media (hover: none), (pointer: coarse)' in css
    assert 'transform: translateY(-3px)' in css
    assert 'outline-offset: 3px' in css
