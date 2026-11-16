from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text('utf-8')


def test_report_archive_is_available_to_logged_in_roles_and_downloads_check_scope():
    source = read('backend/app/web_app.py')
    for route in ("@admin_bp.get('/report-archive')",
                  "@admin_bp.get('/report-archive/<int:document_id>/download')",
                  "@admin_bp.get('/report-archive/my-work.pdf')"):
        assert route in source
    assert "@login_required\ndef report_archive(" in source
    assert "def _report_archive_can_view(user, document)" in source
    assert "document.owner_user_id == user.id" in source
    assert "abort(404)" in source[source.index("def report_archive_download"):source.index("def report_archive_my_work_pdf")]


def test_year_delete_requires_persisted_verified_backup_and_zip_contains_only_direction_reports():
    source = read('backend/app/web_app.py')
    backup = source[source.index("def report_archive_year_backup"):source.index("def report_archive_year_delete")]
    delete = source[source.index("def report_archive_year_delete"):source.index("@admin_bp.get('/analytics-report.pdf')")]
    assert "report_type='direction'" in backup
    assert "_file_sha256(backup_path)" in backup
    assert "archive.write(path, archive_name)" in backup
    assert "MANIFEST.txt" in backup
    assert "ReportArchiveBackup(" in backup
    assert "ReportArchiveBackup.query.filter_by" in delete
    assert "backup.file_sha256" in delete
    assert "report_type='direction'" in delete
    assert "backup_root" in delete


def test_archive_page_has_year_month_direction_filters_and_role_sensitive_controls():
    page = read('frontend/templates/events/report_archive.html')
    assert 'name="year"' in page and 'name="month"' in page and 'name="direction"' in page
    assert "report_archive_year_backup" in page
    assert "report_archive_year_delete" in page
    assert "report_archive_my_work_pdf" in page
    assert 'Скачать PDF' in page


def test_report_archive_metadata_is_persisted_on_system_bind():
    source = read('backend/app/database/system.py')
    init = read('backend/app/database/__init__.py')
    for field in ('report_type', 'report_key', 'report_title', 'owner_user_id', 'direction_id',
                  'relative_path', 'file_sha256', 'signature_code', 'report_year', 'report_month'):
        assert field in source
    assert '__bind_key__ = "system"' in source
    assert 'ReportArchiveDocument' in init and 'ReportArchiveBackup' in init and 'ReportArchiveDocumentDirection' in init


def test_pdf_reports_hide_gost_and_signature_requisites_while_audit_records_remain():
    pdf_source = read('backend/app/services/report_pdfs.py')
    source = read('backend/app/web_app.py')
    for hidden_requisite in (
        'ГОСТ Р 7.0.97-2025', 'Регистрационный номер:', 'Дата документа:',
        'Подписант:', 'Оформление реквизитов:', 'Документ №', 'Сформирован:',
        'SHA-256:', 'Подписано:', 'НЕ ПОДПИСАН',
    ):
        assert hidden_requisite not in pdf_source
    assert "'is_official_signature': False" in source
    assert 'db.session.add(signature_row)' in source
    assert 'signature_row.document_sha256 = hashlib.sha256(pdf_bytes).hexdigest()' in source


def test_archive_navigation_is_present_for_staff_and_other_logged_in_roles():
    nav = read('frontend/templates/shared/base.html')
    assert "url_for('admin.report_archive')" in nav
    assert "ep.startswith('admin.report_archive')" in nav


def test_cross_direction_event_documents_are_scoped_through_many_to_many_mapping():
    source = read('backend/app/web_app.py')
    assert 'direction_ids=get_quota_direction_ids(event_id)' in source
    assert 'ReportArchiveDocumentDirection(document_id=row.id, direction_id=value)' in source
    assert 'direction_document_ids = db.session.query(ReportArchiveDocumentDirection.document_id)' in source
    assert 'ReportArchiveDocumentDirection.direction_id.in_(allowed_direction_ids)' not in source


def test_zip_snapshot_is_rechecked_before_delete_to_prevent_unbacked_new_reports_from_being_removed():
    source = read('backend/app/web_app.py')
    backup = source[source.index('def report_archive_year_backup'):source.index("@admin_bp.post('/report-archive/year/<int:year>/delete')")]
    delete = source[source.index('def report_archive_year_delete'):source.index("@admin_bp.get('/analytics-report.pdf')")]
    assert 'document_set_sha256=document_set_hash' in backup
    assert 'current_document_set_hash != backup.document_set_sha256' in delete
    assert 'ReportArchiveDocument.signature_code.isnot(None)' in delete
    assert 'files_to_delete = []' in delete
    assert 'db.session.commit()' in delete


def test_staff_can_only_download_personal_work_documents_not_direction_or_event_pdfs():
    source = read('backend/app/web_app.py')
    can_view = source[source.index('def _report_archive_can_view'):source.index('def _report_archive_file')]
    archive = source[source.index("def report_archive(current_user)"):source.index("def report_archive_download")]
    assert "document.report_type == 'staff_work' and document.owner_user_id == user.id" in can_view
    assert "query = query.filter(own_work_filter)" in archive
    assert "direction_work_filter" not in archive
    assert "directions = []" in archive


def test_only_supported_employee_and_observer_modes_are_assignable_from_staff_accounts():
    staff_source = read('backend/app/services/staff_routes.py')
    template = read('frontend/templates/staff/accounts.html')
    migration = read('backend/app/database/helpers.py')
    assert "ACCOUNT_RANKS = {'employee_all': 'Сотрудник — все направления', 'employee': 'Сотрудник одного направления', 'observer': 'Наблюдатель'}" in staff_source
    assert 'if rank not in ACCOUNT_RANKS:' in staff_source
    assert "User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value])" in staff_source
    assert "UserRole.ADMIN.value if rank == 'admin'" not in staff_source
    assert "'admin': 'Администратор'" not in staff_source
    assert "migrate_staff_account_roles(settings.PEOPLE_DATABASE_PATH)" in migration
    assert 'Сотрудники и наблюдатели' in template


def test_legacy_archive_admin_accounts_are_downgraded_without_inheriting_access():
    migration = read('backend/app/database/helpers.py')
    assert 'UPDATE users SET role=\'staff\', staff_rank=\'employee\'' in migration
    assert "WHERE role='admin'" in migration
    assert 'DELETE FROM staff_grants' in migration
    assert "assigned_direction_id=NULL" in migration


def test_pdf_layout_uses_standard_body_text_and_top_centered_page_numbers():
    pdf_source = read('backend/app/services/report_pdfs.py')
    assert 'fontSize=12, leading=18, firstLineIndent=12.5 * mm' in pdf_source
    assert 'alignment=TA_JUSTIFY' in pdf_source
    assert 'canvas.drawCentredString(width / 2, height - 10 * mm, str(doc.page))' in pdf_source
    assert 'canvas.drawRightString(width - 18 * mm, 17 * mm, f"Страница {doc.page}")' not in pdf_source


def test_event_archive_rows_display_all_linked_direction_names():
    source = read('backend/app/web_app.py')
    template = read('frontend/templates/events/report_archive.html')
    assert 'document_direction_names = {' in source
    assert "document_direction_names=document_direction_names" in source
    assert "document_direction_names.get(item.id, 'Личный отчёт')" in template


def test_new_staff_accounts_use_the_three_configured_employee_modes():
    staff_source = read('backend/app/services/staff_routes.py')
    assert "ACCOUNT_RANKS = {'employee_all': 'Сотрудник — все направления', 'employee': 'Сотрудник одного направления', 'observer': 'Наблюдатель'}" in staff_source
    assert "user.role = UserRole.OBSERVER.value if rank == 'observer' else UserRole.STAFF.value" in staff_source
    assert 'rank not in ACCOUNT_RANKS' in staff_source


def test_archive_admin_has_explicit_year_backup_and_delete_button_with_server_side_role_guard():
    source = read('backend/app/web_app.py')
    template = read('frontend/templates/events/report_archive.html')
    login_guard = source[source.index('def login_required'):source.index('def super_admin_required')]
    backup = source[source.index("def report_archive_year_backup"):source.index("def report_archive_year_delete")]
    delete = source[source.index("def report_archive_year_delete"):source.index("@admin_bp.get('/analytics-report.pdf')")]
    assert "UserRole.ADMIN.value" not in login_guard
    assert 'def archive_year_admin_required' in source
    assert 'current_user.role != UserRole.SUPER_ADMIN.value' in source[source.index('def archive_year_admin_required'):source.index('def _lesson_access_scope')]
    assert '@archive_year_admin_required' in source[source.index("@admin_bp.get('/report-archive/year/"):source.index("@admin_bp.get('/analytics-report.pdf')")]
    assert 'created_by_user_id=current_user.id' in backup
    assert 'created_by_user_id=current_user.id' in delete
    assert 'Удалить отчёты за {{ selected_year }} год' in template
    assert '{% if can_manage_years and selected_year %}' in template
