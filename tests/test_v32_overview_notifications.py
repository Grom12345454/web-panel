from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_overview_layout_does_not_depend_on_legacy_ui_version_11():
    css = read("frontend/assets/styles/shared/overview-notifications-v32.css")
    template = read("frontend/templates/shared/base.html")
    assert 'data-ui-version="14"' in template
    assert 'body.uc-body.is-dashboard-page .mission-kpis' in css
    assert 'body.uc-body.is-dashboard-page .mission-workspace-grid' in css
    assert 'body.uc-body.is-dashboard-page .mission-analytics-grid' in css
    assert 'body.uc-body.is-dashboard-page .mission-bot-grid' in css
    assert 'body.uc-body.is-dashboard-page .mission-bot-head' in css
    assert 'data-ui-version="11"' not in css


def test_notification_open_button_and_detail_body_have_explicit_styles():
    css = read("frontend/assets/styles/shared/overview-notifications-v32.css")
    template = read("frontend/templates/system/notifications.html")
    assert 'class="alert-open-details"' in template
    assert 'class="alert-modal-body"' in template
    assert 'body.uc-body[data-page="admin-notifications"] .alert-open-details' in css
    assert 'body.uc-body[data-page="admin-notifications"] .alert-modal-body' in css
    assert 'body.uc-body.has-system-toast .app-shell .main .page' not in css
    assert '136px' not in css
    assert '@media (max-width: 680px)' in css


def test_v32_styles_are_in_the_site_bundle_after_the_previous_design_layer():
    build = read("scripts/build_assets.py")
    css = read("static/css/site.bundle.css")
    assert "shared/overview-notifications-v32.css" in build
    assert css.rfind("V32: render the current dashboard") > css.rfind("V31 — Kinetic cinema layer")


def test_live_toast_does_not_reserve_document_space_and_cleans_up():
    js = read("frontend/assets/scripts/portal/notifications.js")
    bundle = read("static/js/site.bundle.js")
    for needle in ('toastTimer', 'item.remove()'):
        assert needle in js
        assert needle in bundle
    assert 'has-system-toast' not in js
    assert 'has-system-toast' not in bundle
