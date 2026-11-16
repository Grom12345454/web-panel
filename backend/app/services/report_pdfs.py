"""PDF exports for event, direction and staff activity reports.

Reports include a compact decorative document seal and a translucent brand
watermark. Administrative signature evidence remains in the private audit log
and is intentionally not printed into exported PDFs.
"""
from __future__ import annotations

from html import escape
import math
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _register_fonts() -> tuple[str, str]:
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for regular_path, bold_path in candidates:
        if Path(regular_path).is_file() and Path(bold_path).is_file():
            try:
                if "ReportCyrillic" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("ReportCyrillic", regular_path))
                if "ReportCyrillic-Bold" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("ReportCyrillic-Bold", bold_path))
                return "ReportCyrillic", "ReportCyrillic-Bold"
            except Exception:
                continue
    # This fallback is useful on minimal hosts, although a Cyrillic-capable
    # system font is strongly recommended for production deployments.
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = _register_fonts()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontName=FONT_BOLD,
            fontSize=14, leading=18, textColor=colors.HexColor("#142B45"),
            alignment=TA_LEFT, spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=base["Normal"], fontName=FONT,
            fontSize=12, leading=18, textColor=colors.HexColor("#52677D"),
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "ReportSection", parent=base["Heading2"], fontName=FONT_BOLD,
            fontSize=14, leading=18, textColor=colors.HexColor("#183B5B"),
            spaceBefore=10, spaceAfter=6, keepWithNext=False,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=base["BodyText"], fontName=FONT,
            fontSize=12, leading=18, firstLineIndent=12.5 * mm,
            alignment=TA_JUSTIFY, textColor=colors.HexColor("#25384C"),
        ),
        "small": ParagraphStyle(
            "ReportSmall", parent=base["BodyText"], fontName=FONT,
            fontSize=8, leading=10, textColor=colors.HexColor("#52677D"),
        ),
        "cell": ParagraphStyle(
            "ReportCell", parent=base["BodyText"], fontName=FONT,
            fontSize=8.5, leading=10.5, textColor=colors.HexColor("#25384C"),
        ),
        "cell_bold": ParagraphStyle(
            "ReportCellBold", parent=base["BodyText"], fontName=FONT_BOLD,
            fontSize=8.5, leading=10.5, textColor=colors.HexColor("#183B5B"),
        ),
        "center": ParagraphStyle(
            "ReportCenter", parent=base["BodyText"], fontName=FONT,
            fontSize=8.5, leading=10.5, alignment=TA_CENTER,
            textColor=colors.HexColor("#25384C"),
        ),
    }


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    text = "—" if value is None or value == "" else str(value)
    safe = escape(text).replace("\r\n", "\n").replace("\n", "<br/>")
    return Paragraph(safe, style)


def _table(rows: list[list[Any]], widths: list[float], *, header: bool = True) -> LongTable:
    styles = _styles()
    prepared = []
    for row_index, row in enumerate(rows):
        prepared.append([
            cell if isinstance(cell, Paragraph) else _p(
                cell, styles["cell_bold"] if header and row_index == 0 else styles["cell"]
            )
            for cell in row
        ])
    table = LongTable(prepared, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#8CA4BC")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#DDE5ED")),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F6")))
    table.setStyle(TableStyle(commands))
    return table


def _watermark_path() -> Path:
    """Use the single canonical watermark asset shared by the application."""
    return Path(__file__).resolve().parents[3] / "static" / "favicon-watermark.png"


class DocumentSeal(Flowable):
    """Decorative student-council document seal; contains no signer details."""

    def __init__(self):
        super().__init__()
        self.height = 29 * mm
        self.width = 0

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        return avail_width, self.height

    def draw(self):
        canvas = self.canv
        diameter = 25 * mm
        radius = diameter / 2
        cx = self.width - radius - 2 * mm
        cy = self.height / 2
        navy = colors.HexColor("#244D70")
        teal = colors.HexColor("#299C9A")
        pale = colors.HexColor("#A9C9D8")

        canvas.saveState()
        # A restrained double-ring emblem with fine radial markers.
        canvas.setStrokeColor(navy)
        canvas.setLineWidth(1.15)
        canvas.circle(cx, cy, radius, stroke=1, fill=0)
        canvas.setStrokeColor(teal)
        canvas.setLineWidth(0.55)
        canvas.circle(cx, cy, radius - 1.6 * mm, stroke=1, fill=0)
        canvas.setStrokeColor(pale)
        canvas.setLineWidth(0.7)
        for angle in range(0, 360, 30):
            radians = math.radians(angle)
            inner = radius - 2.5 * mm
            outer = radius - 1.7 * mm
            canvas.line(
                cx + math.cos(radians) * inner,
                cy + math.sin(radians) * inner,
                cx + math.cos(radians) * outer,
                cy + math.sin(radians) * outer,
            )

        canvas.setFillColor(navy)
        canvas.setFont(FONT_BOLD, 4.0)
        canvas.drawCentredString(cx, cy + 7.0 * mm, "СТУДЕНЧЕСКИЙ СОВЕТ")

        # Open-book symbol drawn as vector paths, with a small rising star.
        canvas.setStrokeColor(teal)
        canvas.setLineWidth(1.0)
        book = canvas.beginPath()
        book.moveTo(cx, cy - 3.2 * mm)
        book.curveTo(cx - 2.0 * mm, cy - 1.8 * mm, cx - 4.3 * mm, cy - 1.4 * mm, cx - 6.0 * mm, cy - 2.0 * mm)
        book.lineTo(cx - 6.0 * mm, cy + 2.0 * mm)
        book.curveTo(cx - 3.5 * mm, cy + 2.8 * mm, cx - 1.5 * mm, cy + 1.6 * mm, cx, cy + 0.5 * mm)
        book.curveTo(cx + 1.5 * mm, cy + 1.6 * mm, cx + 3.5 * mm, cy + 2.8 * mm, cx + 6.0 * mm, cy + 2.0 * mm)
        book.lineTo(cx + 6.0 * mm, cy - 2.0 * mm)
        book.curveTo(cx + 4.3 * mm, cy - 1.4 * mm, cx + 2.0 * mm, cy - 1.8 * mm, cx, cy - 3.2 * mm)
        canvas.drawPath(book, stroke=1, fill=0)
        canvas.setStrokeColor(navy)
        canvas.setLineWidth(0.65)
        canvas.line(cx, cy + 0.4 * mm, cx, cy - 3.0 * mm)

        canvas.setFillColor(teal)
        canvas.setFont(FONT_BOLD, 4.7)
        canvas.drawCentredString(cx, cy - 7.2 * mm, "ОТЧЁТ")
        canvas.setFillColor(navy)
        canvas.circle(cx, cy + 4.7 * mm, 0.55 * mm, stroke=0, fill=1)
        canvas.restoreState()


def _append_document_seal(story: list[Any]) -> list[Any]:
    """Append only the decorative seal; signer and approval metadata stay private."""
    return story + [Spacer(1, 3 * mm), DocumentSeal()]


def _draw_page(canvas, doc) -> None:
    """Draw a visible but translucent logo illustration behind report content."""
    canvas.saveState()
    width, height = doc.pagesize

    # The watermark is a transparent PNG derived from the site's favicon.ico.
    # Drawing it in onPage keeps it behind all report text and table content.
    watermark = _watermark_path()
    if watermark.is_file():
        size = 88 * mm
        canvas.drawImage(
            ImageReader(str(watermark)),
            (width - size) / 2,
            (height - size) / 2,
            width=size,
            height=size,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )

    canvas.setStrokeColor(colors.HexColor("#D8E1EA"))
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, height - 17 * mm, width - 18 * mm, height - 17 * mm)

    # Page number on pages after the first is centered in the top margin.
    if getattr(doc, "page", 1) > 1:
        canvas.setFont(FONT, 8)
        canvas.drawCentredString(width / 2, height - 10 * mm, str(doc.page))

    canvas.restoreState()


def _build_pdf(title: str, subtitle: str, story: list[Any], signature: dict[str, Any], *, page_size=A4) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=page_size,
        leftMargin=20 * mm, rightMargin=15 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=title, author="Student App",
        creator="Student App PDF Report Export",
        pageCompression=1,
    )
    styles = _styles()
    # Only the decorative seal is visible; signature evidence and hashes remain private.
    complete_story = [
        _p(title, styles["title"]),
        _p(subtitle, styles["subtitle"]),
        Spacer(1, 5 * mm),
    ] + _append_document_seal(story)
    doc.build(
        complete_story,
        onFirstPage=_draw_page,
        onLaterPages=_draw_page,
    )
    return buffer.getvalue()


def _section(text: str) -> Paragraph:
    return _p(text, _styles()["section"])


def _event_report_story(data: dict[str, Any]) -> list[Any]:
    styles = _styles()
    story: list[Any] = [
        _p(f"ID мероприятия: {data.get('event_id', '—')}", styles["small"]),
        _section("Паспорт мероприятия"),
    ]
    detail_rows = [["Параметр", "Значение"],
        ["Направления", ", ".join(data.get("directions", [])) or "Не привязаны"],
        ["Даты", data.get("dates") or "—"],
        ["Место", data.get("location") or "—"],
        ["Время", data.get("time_range") or "—"],
        ["Лимит мест", data.get("capacity", 0)],
        ["Публикация", data.get("publication_status") or "—"],
    ]
    story.append(_table(detail_rows, [42 * mm, 130 * mm]))
    if data.get("description"):
        story.extend([Spacer(1, 5), _p(f"Описание: {data['description']}", styles["body"])])

    story.append(_section("Итоги участия"))
    metric_rows = [["Записано", "Посетили", "Отсутствовали", "Отменили", "Отказались", "Всего записей"], [
        data.get("counts", {}).get("registered", 0),
        data.get("counts", {}).get("attended", 0),
        data.get("counts", {}).get("absent", 0),
        data.get("counts", {}).get("cancelled", 0),
        data.get("counts", {}).get("declined", 0),
        data.get("counts", {}).get("total", 0),
    ]]
    story.append(_table(metric_rows, [29 * mm, 29 * mm, 29 * mm, 29 * mm, 29 * mm, 29 * mm]))

    story.append(_section("Список участников и посещаемость"))
    attendance = [["Дата", "Участник", "Группа", "Статус"]]
    attendance.extend([[row.get("date", "—"), row.get("name", "—"), row.get("group", "—"), row.get("status", "—")]
                       for row in data.get("attendance", [])])
    if len(attendance) == 1:
        attendance.append(["—", "Записей участников нет", "—", "—"])
    story.append(_table(attendance, [26 * mm, 72 * mm, 30 * mm, 44 * mm]))

    story.append(_section("Официальные отказы от участия"))
    decline_rows = [["Участник", "Дата фиксации", "Сведения"]]
    decline_rows.extend([[row.get("name", "—"), row.get("date", "—"), "Причина сохранена в системе и не включена в отчёт"]
                         for row in data.get("declines", [])])
    if len(decline_rows) == 1:
        decline_rows.append(["—", "—", "Отказов от участия нет"])
    story.append(_table(decline_rows, [55 * mm, 48 * mm, 71 * mm]))

    story.append(_section("Действия направлений и мероприятия из журнала базы данных"))
    story.append(_p(
        "Включены все найденные записи StudentActivity по мероприятию и связанным с ним направлениям. "
        "Личные причины отказов в документ не выводятся.", styles["small"]
    ))
    actions = [["Когда (UTC)", "Направление", "Тип", "Описание действия"]]
    actions.extend([[row.get("created_at", "—"), row.get("direction", "—"), row.get("action", "—"), row.get("description", "—")]
                    for row in data.get("actions", [])])
    if len(actions) == 1:
        actions.append(["—", "—", "—", "История действий не найдена."])
    story.append(_table(actions, [25 * mm, 28 * mm, 27 * mm, 94 * mm]))
    return story



def build_event_report_pdf(data: dict[str, Any], signature: dict[str, Any]) -> bytes:
    story = _event_report_story(data)
    return _build_pdf(data.get("title") or "Отчёт по мероприятию", "ИТОГОВЫЙ ОТЧЁТ ПО МЕРОПРИЯТИЮ", story, signature)


def build_direction_report_pdf(data: dict[str, Any], signature: dict[str, Any]) -> bytes:
    styles = _styles()
    totals = data.get("attendance_totals", {})
    story: list[Any] = [
        _section("Общая информация и сводные показатели направления"),
    ]
    rows = [["Показатель", "Значение"],
            ["Участники", data.get("student_count", 0)],
            ["Мероприятия", data.get("event_count", 0)],
            ["Занятия", data.get("lesson_count", 0)],
            ["Записано на мероприятия", totals.get("registered", 0)],
            ["Посещений", totals.get("attended", 0)],
            ["Пропусков", totals.get("absent", 0)],
            ["Отмен участия", totals.get("cancelled", 0)],
            ["Официальных отказов", totals.get("declined", 0)],]
    story.append(_table(rows, [82 * mm, 90 * mm]))

    story.append(_section("Статусы участников направления"))
    status_rows = [["Статус участника", "Количество"]]
    status_rows.extend([[key, value] for key, value in (data.get("member_status_counts") or {}).items()])
    if len(status_rows) == 1:
        status_rows.append(["Записи не найдены", 0])
    story.append(_table(status_rows, [130 * mm, 42 * mm]))

    story.append(_section("История заявок и решений"))
    decision_rows = [["Решение / статус", "Количество"]]
    decision_rows.extend([[key, value] for key, value in (data.get("application_counts") or {}).items()])
    if len(decision_rows) == 1:
        decision_rows.append(["История решений не найдена", 0])
    story.append(_table(decision_rows, [130 * mm, 42 * mm]))

    story.append(_section("Статусы занятий"))
    lesson_rows = [["Статус занятия", "Количество"]]
    lesson_rows.extend([[key, value] for key, value in (data.get("lesson_status_counts") or {}).items()])
    if len(lesson_rows) == 1:
        lesson_rows.append(["Занятий нет", 0])
    story.append(_table(lesson_rows, [130 * mm, 42 * mm]))

    story.append(_section("Все мероприятия направления (каждое мероприятие имеет отдельный отчёт)"))
    events = [["Мероприятие", "Даты", "Записи", "Были", "Не были", "Отмены", "Отказы"]]
    events.extend([[row.get("title", "—"), row.get("dates", "—"), row.get("participants", 0),
                    row.get("attended", 0), row.get("absent", 0), row.get("cancelled", 0),
                    row.get("declined", 0)] for row in data.get("events", [])])
    if len(events) == 1:
        events.append(["Мероприятий нет", "—", 0, 0, 0, 0, 0])
    story.append(_table(events, [52 * mm, 29 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 19 * mm]))

    # Append the same complete event report used by the individual event PDF:
    # passport, attendance, declines and relevant activity journal. This keeps
    # a direction PDF self-contained instead of requiring separate downloads.
    event_reports = data.get("event_reports") or []
    for event_report in event_reports:
        story.append(PageBreak())
        story.append(_section("ПОДРОБНЫЙ ОТЧЁТ ПО МЕРОПРИЯТИЮ"))
        story.extend(_event_report_story(event_report))

    return _build_pdf(data.get("name") or "Отчёт по направлению", "ПОЛНЫЙ СВОДНЫЙ ОТЧЁТ ПО НАПРАВЛЕНИЮ", story, signature)


def build_staff_journal_pdf(data: dict[str, Any], signature: dict[str, Any]) -> bytes:
    styles = _styles()
    story: list[Any] = [
        _p(f"Записей в выборке: {data.get('total', 0)}", styles["small"]),
        _section("Параметры выборки"),
        _p(data.get("filter_summary") or "Фильтры не заданы; применены стандартные условия журнала сотрудников.", styles["body"]),
        Spacer(1, 5),
        _section("Журнал действий сотрудников"),
    ]
    entries = [["Когда (UTC)", "Сотрудник / аккаунт", "Что сделал", "Раздел"]]
    entries.extend([[row.get("created_at", "—"), row.get("account", "—"), row.get("action", "—"), row.get("section", "—")]
                    for row in data.get("entries", [])])
    if len(entries) == 1:
        entries.append(["—", "—", "Нет действий по выбранным фильтрам", "—"])
    story.append(_table(entries, [32 * mm, 45 * mm, 105 * mm, 75 * mm]))
    return _build_pdf("Журнал действий сотрудников", "КОНФИДЕНЦИАЛЬНО · ЖУРНАЛ СОТРУДНИКОВ", story, signature,
                      page_size=landscape(A4))



def build_analytics_report_pdf(data: dict[str, Any], signature: dict[str, Any]) -> bytes:
    """Signed general report of site-level activity and operational metrics."""
    styles = _styles()
    totals = data.get("totals", {})
    story: list[Any] = [
        _section("Сводные показатели сайта"),
    ]
    metric_rows = [["Показатель", "Значение"]]
    metric_labels = {
        "directions": "Направлений", "students": "Зарегистрированных студентов",
        "events": "Мероприятий", "lessons": "Занятий", "activities": "Бизнес-действий",
        "staff_actions": "Действий сотрудников", "bot_business_actions": "Бизнес-действий ботов",
        "bot_system_events": "Технических событий ботов", "declines": "Отказов от мероприятий",
        "signed_reports": "Выпущенных подписанных отчётов",
    }
    metric_rows.extend([[label, totals.get(key, 0)] for key, label in metric_labels.items()])
    story.append(_table(metric_rows, [112 * mm, 60 * mm]))

    story.append(_section("Статистика посещаемости"))
    status_labels = {"registered": "Записано", "attended": "Посетили", "absent": "Не посетили", "cancelled": "Отменили", "unknown": "Не указан статус"}
    attendance_rows = [["Статус", "Количество"]]
    attendance_rows.extend([[status_labels.get(key, key), value] for key, value in (data.get("attendance") or {}).items()])
    if len(attendance_rows) == 1:
        attendance_rows.append(["Записей посещаемости нет", 0])
    story.append(_table(attendance_rows, [112 * mm, 60 * mm]))

    story.append(_section("Заявления и решения по направлениям"))
    decision_labels = {"pending": "На рассмотрении", "interview": "Собеседование",
                       "active": "Активировано", "approved": "Принято",
                       "rejected": "Отклонено", "withdrawn": "Отозвано"}
    decision_rows = [["Решение", "Количество"]]
    decision_rows.extend([[decision_labels.get(key, key), value]
                          for key, value in (data.get("application_decisions") or {}).items()])
    if len(decision_rows) == 1:
        decision_rows.append(["История решений не найдена", 0])
    story.append(_table(decision_rows, [112 * mm, 60 * mm]))

    story.append(_section("Показатели по каждому направлению"))
    direction_rows = [["Направление", "Участники", "Мероприятий", "Посещений", "Отказов", "Действий"]]
    direction_rows.extend([[row.get("name", "—"), row.get("students", 0), row.get("events", 0),
                            row.get("visits", 0), row.get("declines", 0), row.get("actions", 0)]
                           for row in data.get("directions", [])])
    if len(direction_rows) == 1:
        direction_rows.append(["Направлений нет", 0, 0, 0, 0, 0])
    story.append(_table(direction_rows, [60 * mm, 23 * mm, 23 * mm, 23 * mm, 23 * mm, 27 * mm]))
    return _build_pdf("Общая аналитика сайта", "СВОДНЫЙ ОТЧЁТ ПО ВСЕМУ САЙТУ", story, signature)


def build_bot_journal_pdf(data: dict[str, Any], signature: dict[str, Any]) -> bytes:
    """Signed journal of bot business actions and transport/integration events."""
    styles = _styles()
    story: list[Any] = [
        _p(f"Всего записей: {data.get('total', 0)}", styles["small"]),
        _section("Состав отчёта"),
        _p(data.get("filter_summary") or "Бизнес-действия ботов и технические события интеграций.", styles["body"]),
        _p(f"Бизнес-действий: {data.get('business_actions', 0)} · Технических событий: {data.get('system_events', 0)}", styles["small"]),
        Spacer(1, 5), _section("Журнал действий ботов и интеграций"),
    ]
    entries = [["Когда (UTC)", "Источник / платформа", "Исполнитель", "Действие / объект", "Статус", "мс"]]
    entries.extend([[row.get("created_at", "—"), f"{row.get('source', '—')} / {row.get('platform', '—')}",
                     row.get("actor", "—"), f"{row.get('action', '—')} · {row.get('object', '—')}",
                     row.get("status", "—"), row.get("duration_ms", "—")]
                    for row in data.get("entries", [])])
    if len(entries) == 1:
        entries.append(["—", "—", "—", "Действий не найдено", "—", "—"])
    story.append(_table(entries, [29 * mm, 48 * mm, 38 * mm, 90 * mm, 27 * mm, 17 * mm]))
    return _build_pdf("Журнал действий ботов", "КОНФИДЕНЦИАЛЬНО · ЖУРНАЛ БОТОВ И ИНТЕГРАЦИЙ", story, signature,
                      page_size=landscape(A4))
