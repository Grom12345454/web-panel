from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mobile_compatibility_layer_is_the_last_student_css_source():
    build = read("scripts/build_assets.py")
    manifest = read("frontend/asset-manifest.json")
    compat = read("frontend/assets/styles/student/student-mobile-compat-2026.css")
    bundle = read("static/css/student-app.bundle.css")
    assert "student/student-mobile-compat-2026.css" in build
    assert "student/student-mobile-compat-2026.css" in manifest
    assert "cross-generation device compatibility" in compat
    assert bundle.rfind("BEGIN frontend/assets/styles/student/student-mobile-compat-2026.css") > bundle.rfind(
        "BEGIN frontend/assets/styles/student/student-responsive-2026.css"
    )


def test_old_webkit_fallbacks_and_sub_320px_viewports_are_supported():
    compat = read("frontend/assets/styles/student/student-mobile-compat-2026.css")
    html = read("frontend/templates/student/student_app.html")
    foundation = read("frontend/assets/styles/student/student-app-2026.css")
    v9 = read("frontend/assets/styles/student/student-app-v9.css")
    assert '<html lang="ru" class="student-app-document">' in html
    assert "min-width: 0 !important" in compat
    assert "constant(safe-area-inset-top)" in compat
    assert "env(safe-area-inset-top, 0px)" in compat
    assert "overflow-x: hidden" in compat
    assert "overflow-x: clip" in compat
    assert "min-width:320px" not in compat
    assert "min-width: 320px" not in foundation + v9 + compat
    assert "html:has(body" not in "\n".join(
        read(path)
        for path in (
            "frontend/assets/styles/student/student-app-modern.css",
            "frontend/assets/styles/student/campus-space-background-v48.css",
            "frontend/assets/styles/student/student-responsive-2026.css",
            "frontend/assets/styles/student/student-mobile-compat-2026.css",
        )
    )


def test_device_runtime_profile_tracks_viewport_keyboard_and_browser_capabilities():
    js = read("frontend/assets/scripts/student/student_app.js")
    assert "body.dataset.deviceFamily=ios?'ios':android?'android':'other'" in js
    assert "body.dataset.formFactor=tablet?'tablet':touch?'handset':'desktop'" in js
    assert "body.dataset.runtime=runtime" in js
    assert "body.dataset.engine=engine" in js
    assert "body.dataset.viewportProfile" in js
    assert "body.classList.toggle('student-keyboard-open',keyboardOpen)" in js
    assert "window.visualViewport" in js
    assert "viewport?.addEventListener('resize'" in js
    assert "viewport?.addEventListener('scroll'" in js
    assert "document.addEventListener('focusin'" in js
    assert "document.addEventListener('focusout'" in js


def test_mobile_layout_preserves_zoom_safe_areas_touch_targets_and_keyboard_space():
    compat = read("frontend/assets/styles/student/student-mobile-compat-2026.css")
    assert "text-size-adjust: auto" in compat
    assert "font-size: 16px !important" in compat
    assert "--student-control-size: 44px" in compat
    assert "student-keyboard-open .mission-bottom-nav" in compat
    assert "horizontal-viewport-segments: 2" in compat
    assert "prefers-reduced-motion: reduce" in compat
    assert "prefers-contrast: more" in compat
    assert "forced-colors: active" in compat


@pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None or shutil.which("chromium") is None,
    reason="Playwright and Chromium are optional browser-test dependencies",
)
@pytest.mark.parametrize(
    "width,height",
    [
        (280, 640),
        (320, 568),
        (344, 720),
        (360, 740),
        (375, 667),
        (390, 844),
        (414, 896),
        (430, 932),
        (540, 800),
        (600, 960),
        (640, 960),
        (667, 375),
        (720, 400),
        (744, 1133),
        (768, 1024),
        (820, 1180),
        (912, 1368),
        (1024, 768),
        (1180, 820),
        (1280, 800),
    ],
)
def test_chromium_mobile_and_tablet_viewport_matrix_has_no_horizontal_page_overflow(width, height):
    from playwright.sync_api import sync_playwright

    css = (ROOT / "static/css/student-app.bundle.css").read_text(encoding="utf-8")
    markup = """<!doctype html>
    <html lang="ru" class="student-app-document">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>
    <body class="student-app-body" data-page="student-app">
      <div class="app" id="app">
        <header class="hero glass"><div class="top"><div><div class="title">Личный кабинет студента с длинным именем</div><div class="muted">Студент · Группа 2026</div></div><div class="mission-mark"><span></span><b></b><em></em></div></div></header>
        <nav class="nav"><button>Мой кабинет</button><button>Календарь</button><button>Заявления</button><button>Руководство</button></nav>
        <main class="student-main" id="student-main">
          <section class="command-metrics"><article class="command-metric"><strong>12</strong><span>Активных направлений</span></article><article class="command-metric"><strong>3</strong><span>Новых уведомления</span></article><article class="command-metric"><strong>42</strong><span>Мероприятия и встречи</span></article></section>
          <section class="command-next-row"><article class="command-next-card"><h3>Следующая миссия</h3><p>Подробная информация о ближайшем мероприятии студенческого совета</p><button class="btn">Открыть календарь</button></article><article class="command-next-card"><h3>Твой путь в команде</h3><p>Информация о заявках и активности</p></article></section>
          <section class="card"><h2>Профиль</h2><label for="profile">Имя</label><input id="profile" class="input" value="Студент"></section>
        </main>
        <nav class="mission-bottom-nav"><button><span>⌂</span><small>Главная</small></button><button><span>▦</span><small>Календарь</small></button><button><span>◫</span><small>Заявления</small></button><button><span>☰</span><small>Ещё</small></button></nav>
      </div>
    </body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=shutil.which("chromium"), args=["--no-sandbox"])
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
            is_mobile=width <= 760,
            has_touch=width <= 1024,
        )
        page.set_content(markup, wait_until="domcontentloaded")
        page.add_style_tag(content=css)
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_timeout(30)
        metrics = page.evaluate(
            """() => ({
              viewport: window.innerWidth,
              documentWidth: document.documentElement.scrollWidth,
              bodyWidth: document.body.scrollWidth,
              appWidth: document.querySelector('#app').getBoundingClientRect().width,
              mainWidth: document.querySelector('#student-main').getBoundingClientRect().width,
              dock: (() => { const r=document.querySelector('.mission-bottom-nav').getBoundingClientRect(); return {left:r.left,right:r.right,width:r.width}; })(),
              inputFont: parseFloat(getComputedStyle(document.querySelector('#profile')).fontSize)
            })"""
        )
        browser.close()
    assert metrics["documentWidth"] <= metrics["viewport"] + 1, (width, height, metrics)
    assert metrics["appWidth"] <= metrics["viewport"] + 1, (width, height, metrics)
    assert metrics["mainWidth"] <= metrics["viewport"] + 1, (width, height, metrics)
    assert metrics["inputFont"] >= 16, (width, height, metrics)


@pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None or shutil.which("chromium") is None,
    reason="Playwright and Chromium are optional browser-test dependencies",
)
def test_runtime_profile_detects_ios_android_webview_and_virtual_keyboard_state():
    from playwright.sync_api import sync_playwright

    profile_js = read("frontend/assets/scripts/student/student_app.js").split(
        "function applyTelegramTheme()", 1
    )[0]
    ios_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    android_ua = (
        "Mozilla/5.0 (Linux; Android 13; SM-S918B Build/TP1A) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/120.0.0.0 Mobile Safari/537.36 wv"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=shutil.which("chromium"), args=["--no-sandbox"])
        ios_page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=ios_ua,
            is_mobile=True,
            has_touch=True,
        )
        ios_page.set_content(
            '<html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>'
            '<body class="student-app-body"><input id="field"></body></html>'
        )
        ios_page.add_script_tag(content=profile_js)
        ios_profile = ios_page.evaluate(
            """() => ({family:document.body.dataset.deviceFamily,
                        form:document.body.dataset.formFactor,
                        runtime:document.body.dataset.runtime,
                        viewport:document.body.dataset.viewportProfile})"""
        )
        assert ios_profile["family"] == "ios"
        assert ios_profile["form"] == "handset"
        assert ios_profile["runtime"] == "browser"
        ios_page.evaluate(
            """() => {
              const vv=window.visualViewport;
              let h=vv.height;
              Object.defineProperty(vv,'height',{configurable:true,get:()=>h});
              document.querySelector('#field').focus();
              h=400;
              vv.dispatchEvent(new Event('resize'));
            }"""
        )
        ios_page.wait_for_timeout(50)
        assert ios_page.locator("body").evaluate("el=>el.classList.contains('student-keyboard-open')")

        android_page = browser.new_page(
            viewport={"width": 412, "height": 915},
            user_agent=android_ua,
            is_mobile=True,
            has_touch=True,
        )
        android_page.set_content('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body class="student-app-body"></body></html>')
        android_page.add_script_tag(content=profile_js)
        android_profile = android_page.evaluate(
            """() => ({family:document.body.dataset.deviceFamily,
                        form:document.body.dataset.formFactor,
                        runtime:document.body.dataset.runtime,
                        engine:document.body.dataset.engine})"""
        )
        browser.close()
    assert android_profile["family"] == "android"
    assert android_profile["form"] == "handset"
    assert android_profile["runtime"] == "webview"
    assert android_profile["engine"] == "blink"
