from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_messenger_monitoring_uses_shared_site_bundle_once():
    base = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    page = (ROOT / "frontend/templates/system/messenger_monitoring.html").read_text(encoding="utf-8")
    bundle_src = "filename='js/site.bundle.js'"
    assert base.count(bundle_src) == 1
    assert bundle_src not in page
    assert "{% block scripts %}" not in page

def test_messenger_monitoring_logic_remains_in_the_shared_bundle():
    build = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
    bundle = (ROOT / "static/js/site.bundle.js").read_text(encoding="utf-8")
    assert "portal/messenger-monitoring-v63.js" in build
    assert "BEGIN frontend/assets/scripts/portal/messenger-monitoring-v63.js" in bundle
