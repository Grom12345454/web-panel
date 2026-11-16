"""Regression checks for the redesigned closed-order archive upload modal."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_order_upload_form_is_inside_accessible_modal():
    template = (ROOT / "frontend/templates/orders/archive.html").read_text("utf8")
    assert 'id="order-upload-modal" data-order-modal hidden aria-hidden="true"' in template
    assert 'role="dialog" aria-modal="true"' in template
    assert 'data-order-modal-open' in template
    assert 'data-order-modal-close' in template
    assert 'id="orders-upload-form" data-order-upload-form' in template
    assert 'enctype="multipart/form-data"' in template
    assert 'name="csrf_token" value="{{ csrf_token() }}"' in template
    assert 'accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"' in template


def test_archive_uses_new_bundled_css_and_modal_javascript():
    builder = (ROOT / "scripts/build_assets.py").read_text("utf8")
    css = (ROOT / "static/css/site.bundle.css").read_text("utf8")
    js = (ROOT / "static/js/site.bundle.js").read_text("utf8")
    source_js = (ROOT / "frontend/assets/scripts/portal/orders-archive.js").read_text("utf8")
    assert "portal/orders-archive.css" in builder
    assert "portal/orders-archive.js" in builder
    assert ".orders-modal-backdrop[hidden]" in css
    assert "const openModal" in js
    assert "event.key === 'Escape'" in source_js
    assert "data-order-search" in source_js
