from pathlib import Path

root = Path('/mnt/data/work_v1917')
template_path = root / 'frontend/templates/statistics/overview.html'
s = template_path.read_text(encoding='utf-8')

# Replace overview and directions with a single reusable per-direction table view.
start = s.index("{% if active_section == 'overview' %}")
end = s.index("{% if active_section == 'attendance' %}")
combined = r'''{% if active_section == 'overview' or active_section == 'directions' %}
<section class="statistics-panel active" role="tabpanel" data-stat-panel="{{ active_section }}">
  <div class="card table-wrap stats-data-table-card direction-table-card">
    <div class="direction-table-tools">
      <label class="direction-filter-field" for="direction-search"><span>Поиск направления</span><input id="direction-search" type="search" placeholder="Название направления…" autocomplete="off"></label>
      <label class="direction-filter-field" for="direction-filter"><span>Показать</span><select id="direction-filter"><option value="all">Все направления</option><option value="visits">Есть посещения</option><option value="events">Есть мероприятия</option><option value="members">Есть активные участники</option></select></label>
      <span id="direction-filter-count" class="direction-filter-count">Показано: {{ direction_stats|length }}</span>
    </div>
    <div class="table-scroll stats-data-table-scroll direction-table-scroll">
      <table id="direction-statistics-table" data-statistics-table>
        <thead><tr><th>#</th><th>Направление</th><th>Активные участники</th><th>Студенты с явкой</th><th>Мероприятия</th><th>Уникальные посещения</th><th>Лидер по посещаемости</th></tr></thead>
        <tbody>
          {% for item in direction_stats %}
          <tr class="direction-stat-row" data-direction-name="{{ item.direction.name|lower|e }}" data-visits="{{ item.visit_count }}" data-events="{{ item.event_count }}" data-members="{{ item.members }}">
            <td class="subtle">{{ loop.index }}</td>
            <td><div class="name-cell">{{ item.direction.name }}</div></td>
            <td><span class="badge">{{ item.members }}</span></td>
            <td><span class="badge {% if item.attenders %}badge-approved{% endif %}">{{ item.attenders }}</span></td>
            <td>{{ item.event_count }}</td>
            <td><span class="badge badge-approved">{{ item.visit_count }}</span></td>
            <td>{% if item.leaders %}{% for leader in item.leaders %}<div class="name-cell">{{ leader.student.full_name }}</div><div class="subtle">{{ leader.visits }} посещений</div>{% if not loop.last %}<div class="subtle">Также лидер</div>{% endif %}{% endfor %}{% else %}<span class="subtle">Нет подтверждённых посещений</span>{% endif %}</td>
          </tr>
          {% else %}
          <tr><td colspan="7"><div class="empty"><h3>Направлений пока нет</h3><p>Данные появятся после создания направлений и регистрации участников.</p></div></td></tr>
          {% endfor %}
          <tr id="direction-filter-empty" hidden><td colspan="7"><div class="empty">По заданным условиям направления не найдены.</div></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
{% endif %}

'''
s = s[:start] + combined + s[end:]

# Attendance: retain the detailed dataset, remove all cards/rankings/diagrams around it.
start = s.index("{% if active_section == 'attendance' %}")
end = s.index("{% if active_section == 'events' %}")
attendance = r'''{% if active_section == 'attendance' %}
<section class="statistics-panel" role="tabpanel" data-stat-panel="attendance">
  <div class="card table-wrap stats-data-table-card attendance-table-card">
    <div class="table-scroll stats-data-table-scroll"><table id="attendance-statistics-table" data-statistics-table>
      <thead><tr><th>#</th><th>Студент</th><th>Учебная группа</th><th>Активных направлений</th><th>Посетил мероприятий</th><th>Недавние мероприятия</th></tr></thead>
      <tbody>
      {% for row in attendance_rows %}<tr><td class="subtle">{{ loop.index }}</td><td><div class="name-cell">{{ row.student.full_name }}</div><div class="subtle">{{ 'Колледж' if row.student.education_type == 'college' else 'Институт' }}</div></td><td>{{ row.student.group or '—' }}</td><td>{{ row.active_directions }}</td><td><span class="badge {% if row.attended %}badge-approved{% endif %}">{{ row.attended }}</span></td><td>{% if row.last_events %}<div class="event-chip-list">{% for title in row.last_events %}<span>{{ title }}</span>{% endfor %}</div>{% else %}<span class="subtle">Нет посещений</span>{% endif %}</td></tr>
      {% else %}<tr><td colspan="6"><div class="empty"><h3>Студентов пока нет</h3><p>Данные появятся после первых подтверждённых посещений.</p></div></td></tr>{% endfor %}
      </tbody>
    </table></div>
  </div>
</section>
{% endif %}

'''
s = s[:start] + attendance + s[end:]

# Events: retain one table and the useful direction filter; remove summary cards and rate diagrams.
start = s.index("{% if active_section == 'events' %}")
end = s.index("{% if active_section == 'declines' %}")
events = r'''{% if active_section == 'events' %}
<section class="statistics-panel" role="tabpanel" data-stat-panel="events">
  <div class="card table-wrap stats-data-table-card direction-table-card">
    <div class="direction-table-tools">
      <label class="direction-filter-field" for="event-direction-filter"><span>Направление</span><select id="event-direction-filter"><option value="all">Все направления</option>{% for direction in directions %}<option value="{{ direction.id }}">{{ direction.name }}</option>{% endfor %}</select></label>
      <span id="event-direction-filter-count" class="direction-filter-count">Показано: {{ event_rows|length }} из {{ event_count }}</span>
    </div>
    <div class="table-scroll stats-data-table-scroll"><table id="event-statistics-table" data-statistics-table>
      <thead><tr><th>#</th><th>Мероприятие</th><th>Даты</th><th>Направлений</th><th>Регистрации</th><th>Посещения</th><th>Явка</th><th>Состояние</th></tr></thead>
      <tbody>
      {% for row in event_rows %}<tr data-direction-ids="{{ row.direction_ids|join(',') }}"><td class="subtle">{{ loop.index }}</td><td><div class="name-cell">{{ row.event.event_title }}</div><div class="subtle">{{ row.event.location or 'Место не указано' }}{% if row.direction_names %} · {{ row.direction_names|join(', ') }}{% endif %}</div></td><td>{% if row.days_in_scope %}<div class="event-chip-list">{% for day in row.days_in_scope %}<span>{{ day.date.strftime('%d.%m.%Y') }}</span>{% endfor %}</div>{% else %}—{% endif %}</td><td>{{ row.directions }}</td><td>{{ row.registrations }}</td><td><span class="badge {% if row.attendees %}badge-approved{% endif %}">{{ row.attendees }}</span></td><td>{{ row.attendance_rate }}%</td><td><span class="badge {% if row.event.is_closed %}badge-rejected{% else %}badge-active{% endif %}">{{ 'Завершено' if row.event.is_closed else 'Активно' }}</span></td></tr>
      {% else %}<tr><td colspan="8"><div class="empty">Мероприятий пока нет.</div></td></tr>{% endfor %}
      <tr id="event-direction-empty" hidden><td colspan="8"><div class="empty">Для выбранного направления мероприятий нет.</div></td></tr>
      </tbody>
    </table></div>
  </div>
</section>
{% endif %}

'''
s = s[:start] + events + s[end:]

# Declines: one data table, no surrounding graphic summary.
start = s.index("{% if active_section == 'declines' %}")
end = s.index("{% endblock %}", start)
declines = r'''{% if active_section == 'declines' %}
<section class="statistics-panel" role="tabpanel" data-stat-panel="declines">
  <div class="card table-wrap stats-data-table-card direction-table-card declines-table-card">
    <div class="direction-table-tools">
      <label class="direction-filter-field" for="decline-direction-filter"><span>Направление</span><select id="decline-direction-filter"><option value="all">Все направления</option>{% for direction in directions %}<option value="{{ direction.id }}">{{ direction.name }}</option>{% endfor %}</select></label>
      <span id="decline-direction-filter-count" class="direction-filter-count">Показано: {{ decline_items|length }} из {{ decline_count }}</span>
    </div>
    <div class="table-scroll stats-data-table-scroll"><table id="decline-statistics-table" data-statistics-table>
      <thead><tr><th>#</th><th>Студент</th><th>Группа</th><th>Мероприятие</th><th>Дата отказа</th><th>Причина</th><th>Всего отказов студента</th></tr></thead>
      <tbody>
      {% for row in decline_items %}<tr data-direction-ids="{{ row.direction_ids|join(',') }}"><td class="subtle">{{ loop.index }}</td><td><div class="name-cell">{% if row.student %}{{ row.student.full_name }}{% else %}Студент #{{ row.decline.student_id }}{% endif %}</div><div class="subtle">ID {{ row.decline.student_id }}</div></td><td>{% if row.student %}{{ row.student.group or '—' }}{% else %}—{% endif %}</td><td><div class="name-cell">{{ row.event.event_title }}</div><div class="subtle">{{ row.event.location or 'Место не указано' }}{% if row.direction_names %} · {{ row.direction_names|join(', ') }}{% endif %}</div></td><td>{{ row.decline.created_at.strftime('%d.%m.%Y %H:%M') if row.decline.created_at else '—' }}</td><td><div class="decline-reason">{{ row.decline.reason }}</div></td><td><span class="badge {% if row.student_decline_count > 1 %}badge-approved{% endif %}">{{ row.student_decline_count }}</span></td></tr>
      {% else %}<tr><td colspan="7"><div class="empty"><h3>Отказов пока нет</h3><p>Отказы студентов появятся здесь после их оформления.</p></div></td></tr>{% endfor %}
      <tr id="decline-direction-empty" hidden><td colspan="7"><div class="empty">Для выбранного направления отказов нет.</div></td></tr>
      </tbody>
    </table></div>
  </div>
</section>
{% endif %}

'''
s = s[:start] + declines + s[end:]
template_path.write_text(s, encoding='utf-8')

# Generate a clean table-only style extension, with the same shell language as Active Students.
css_path = root / 'frontend/assets/styles/portal/statistics-tables-v1917.css'
css = css_path.read_text(encoding='utf-8')
css += r'''

/* v1.9.18 — table-only statistics workspace. */
body.uc-body[data-page^="stats-"] .app-shell {
  min-height: 0 !important;
  height: auto !important;
  align-items: stretch !important;
}
body.uc-body[data-page^="stats-"] .app-shell > .main {
  flex: 0 0 auto !important;
  min-height: 0 !important;
  height: auto !important;
  align-self: stretch !important;
}
body.uc-body[data-page^="stats-"] .app-shell > .main > .page {
  flex: 0 0 auto !important;
  min-height: 0 !important;
  height: auto !important;
  align-self: stretch !important;
  padding-bottom: 18px !important;
}
body.uc-body[data-page^="stats-"] .page:has(.stats-command-header) > * {
  flex: 0 0 auto !important;
  min-height: 0 !important;
  height: auto !important;
}
body.uc-body[data-page^="stats-"] .page .stats-data-table-card {
  margin: 0;
  transform: none !important;
}
body.uc-body[data-page^="stats-"] .page .direction-table-tools {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
  padding: 13px 15px;
  border-bottom: 1px solid rgba(139,190,218,.12);
  background: rgba(5,16,29,.2);
}
body.uc-body[data-page^="stats-"] .page .direction-filter-field {
  display: grid;
  gap: 5px;
  min-width: min(230px, 100%);
  color: #8fa9bd;
  font-size: 10px;
  font-weight: 700;
}
body.uc-body[data-page^="stats-"] .page .direction-filter-field input,
body.uc-body[data-page^="stats-"] .page .direction-filter-field select {
  min-height: 36px;
  max-width: 100%;
  padding: 0 10px;
  border: 1px solid rgba(139,190,218,.18);
  border-radius: 10px;
  background: rgba(5,17,31,.72);
  color: #e8f3fb;
  font: inherit;
}
body.uc-body[data-page^="stats-"] .page .direction-filter-count {
  margin-left: auto;
  padding-bottom: 9px;
  color: #a9c0d0;
  font-size: 10px;
  white-space: nowrap;
}
@media (max-width: 680px) {
  body.uc-body[data-page^="stats-"] .page .direction-table-tools { align-items: stretch; padding: 11px; }
  body.uc-body[data-page^="stats-"] .page .direction-filter-field { flex: 1 1 100%; min-width: 100%; }
  body.uc-body[data-page^="stats-"] .page .direction-filter-count { margin-left: 0; padding-bottom: 0; }
}
'''
css_path.write_text(css, encoding='utf-8')

# Remove the dedicated 3D analytics assets from active production bundles.
for rel in ('portal/statistics-3d-professional-v1914.css',):
    # remove from canonical build source list
    build_path = root / 'scripts/build_assets.py'
    build = build_path.read_text(encoding='utf-8')
    build = build.replace("    # Interactive isometric analytics, 3D comparison charts and responsive depth controls.\n    'portal/statistics-3d-professional-v1914.css',\n", '')
    build = build.replace("    # Camera and presentation controls for the statistics 3D model.\n    'portal/statistics-3d-workspace-v1914.js',\n", '')
    build_path.write_text(build, encoding='utf-8')
    manifest_path = root / 'frontend/asset-manifest.json'
    import json
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for key in ('site_css', 'site_js'):
        manifest['bundles'][key]['files'] = [f for f in manifest['bundles'][key]['files'] if f not in ('portal/statistics-3d-professional-v1914.css', 'portal/statistics-3d-workspace-v1914.js')]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Remove no-longer-used 3D source files so future builds cannot reintroduce the visual system.
(root / 'frontend/assets/styles/portal/statistics-3d-professional-v1914.css').unlink(missing_ok=True)
(root / 'frontend/assets/scripts/portal/statistics-3d-workspace-v1914.js').unlink(missing_ok=True)

# Backend: calculate per-direction aggregates on the overview view as well,
# so the new single overview table is populated from the same real query as the direction view.
backend_path = root / 'backend/app/web_app.py'
backend = backend_path.read_text(encoding='utf-8')
old = '    elif active_section == "directions":\n        # event_directions is built once above for all analytics sections.\n'
new = '    if active_section in ("overview", "directions"):\n        # event_directions is built once above; overview and directions share this same per-direction aggregate.\n'
if old not in backend:
    raise SystemExit('Could not find direction aggregate branch in backend')
backend = backend.replace(old, new, 1)
backend_path.write_text(backend, encoding='utf-8')

# Add release note/update.
(root / 'CHANGELOG_STATISTICS_TABLE_ONLY_V1.9.18_2026-11-16.md').write_text('''# StudSovet v1.9.18 — Table-only statistics\n\n- Replaced the overview and direction visualizations with one unified per-direction table.\n- Removed KPI tiles, 3D relationship model, chart panels, rankings-as-cards, and event/direction schemes from the statistics interface.\n- Kept detailed attendance, events, and declines as tables with common search, sorting, pagination, and CSV export.\n- Overview and Directions now share the same real per-direction aggregates.\n- Removed the dedicated 3D statistics CSS/JS from production asset builds.\n- Tightened statistics page sizing so the app shell and main content use natural content height instead of reserving a viewport-height tail.\n''', encoding='utf-8')
(root / 'UPDATE_TO_V1.9.18_RU.txt').write_text('''StudSovet v1.9.18 — обновление раздела «Статистика»\n\nЧто изменено:\n1. В разделе статистики оставлены только таблицы.\n2. Обзор и подраздел «Направления» используют одну общую таблицу со строкой для каждого направления.\n3. В общей таблице доступны активные участники, студенты с явкой, мероприятия, уникальные посещения и лидеры по посещаемости.\n4. Удалены 3D-модель, графики, диаграммы, схемы и карточки-рейтинги.\n5. Посещаемость, мероприятия и отказы оставлены в виде подробных таблиц.\n6. Сохранены поиск, сортировка, пагинация, фильтры и экспорт CSV.\n7. Сохранены права доступа и фильтрация данных по ролям/направлениям.\n''', encoding='utf-8')
