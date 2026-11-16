"""Isolated regression checks for the 2026 private order archive."""
import ast
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def upload_validation():
    src = ast.parse((ROOT / 'backend/app/services/orders.py').read_text('utf8'))
    item = next(n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == '_validate_order')
    import zipfile
    namespace = {'Path': Path, 'MAX_ORDER_BYTES': 8*1024*1024,
                 'ALLOWED_SUFFIXES': frozenset({'.pdf', '.docx'}),
                 'BytesIO': BytesIO, 'zipfile': zipfile}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[item],type_ignores=[])),'validator','exec'),namespace)
    function = namespace['_validate_order']
    # Werkzeug is part of the deployment requirements, not this test runner.
    # Stub its filename sanitizer only to isolate validation of PDF/DOCX bytes.
    helper = ModuleType('werkzeug.utils')
    helper.secure_filename = lambda name: ''.join(c for c in name if c.isascii() and (c.isalnum() or c in '.-_'))
    wrapper = ModuleType('werkzeug')
    wrapper.utils = helper
    def validate(upload):
        with patch.dict(sys.modules, {'werkzeug': wrapper, 'werkzeug.utils': helper}):
            return function(upload)
    return validate


def test_pdf_validation_and_unsupported_file_type():
    f = upload_validation()
    name, data, mime, suffix = f(SimpleNamespace(filename='приказ.pdf', stream=BytesIO(b'%PDF-1.7\nexample')))
    assert name == 'приказ.pdf'
    assert suffix == '.pdf' and mime == 'application/pdf'
    for filename, content in [('script.exe', b'evil'), ('fake.pdf', b'not_pdf')]:
        try: f(SimpleNamespace(filename=filename, stream=BytesIO(content)))
        except ValueError: pass
        else: assert False, filename


def test_docx_validation_requires_real_package_and_size_limit():
    f = upload_validation()
    output = BytesIO()
    with zipfile.ZipFile(output,'w') as doc:
        doc.writestr('[Content_Types].xml','x')
        doc.writestr('word/document.xml','<w:document/>')
    assert f(SimpleNamespace(filename='science.docx', stream=BytesIO(output.getvalue())))[3] == '.docx'
    for content in (b'junk', b'a'*(8*1024*1024+1)):
        try: f(SimpleNamespace(filename='archive.docx', stream=BytesIO(content)))
        except ValueError: pass
        else: assert False


def test_order_document_delivery_is_scoped_and_durable():
    queue = (ROOT / 'backend/app/services/order_delivery.py').read_text('utf8')
    models = (ROOT / 'backend/app/database/orders.py').read_text('utf8')
    run = (ROOT / 'run.py').read_text('utf8')
    archive = (ROOT / 'frontend/templates/orders/archive.html').read_text('utf8')
    assert "DayParticipation.status.in_(['registered', 'attended'])" in queue
    assert "ScienceAuthor.decision == 'accepted'" in queue
    assert "ScienceSubmission.status.in_(['submitted', 'approved'])" in queue
    assert "student.tg_id" in queue
    assert "'/sendDocument'" in queue
    assert 'class OrderDeliveryJob(db.Model)' in models
    assert 'uq_order_student_platform' in models
    assert 'start_worker("order-documents"' in run
    assert 'url_for(\'orders.retry_order\'' in archive
    assert 'csrf_token()' in archive
    assert 'def dispatch_order(' in (ROOT / 'backend/app/services/orders.py').read_text('utf8')


def test_cleanup_removes_jobs_and_stored_science_orders():
    web = (ROOT / 'backend/app/web_app.py').read_text('utf8')
    assert "OrderDeliveryJob.query.filter(OrderDeliveryJob.order_id.in_(order_ids))" in web
    assert "AdministrativeOrder.query.filter_by(target_kind='science').delete" in web
    assert "AdministrativeOrder.query.filter_by(target_kind='event').delete" in web


def test_retention_chat_and_refresh_behavior():
    notifications = (ROOT / 'backend/app/services/site_notifications.py').read_text('utf8')
    assert 'NOTIFICATION_TTL = timedelta(minutes=90)' in notifications
    chat = (ROOT / 'backend/app/services/science_chat.py').read_text('utf8')
    assert 'ScienceChatMessage.query.filter_by(reading_id=reading.id).delete' in chat
    assert 'reading.is_open = False' in chat
    assert 'window.location.reload' not in (ROOT / 'frontend/assets/scripts/portal/site-sync.js').read_text('utf8')
    assert 'Math.max(120000, STUDENT_SYNC_INTERVAL)' in (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf8')
