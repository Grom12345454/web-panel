from pathlib import Path
import re
p=Path('/mnt/data/work_v1917/frontend/templates/statistics/overview.html')
s=p.read_text(encoding='utf-8')
positions={}
for name in ('overview','attendance','events','declines'):
    m=re.search(rf"(?m)^\{{% if active_section == '{name}' %\}}", s)
    if not m: raise RuntimeError(f'missing section {name}')
    positions[name]=m.start()
end=s.index('{% endblock %}', positions['declines'])
prefix=s[:positions['overview']]
suffix=s[end:]
combined=r'''{% if active_section == 'overview' or active_section == 'directions' %}
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

{% if active_section == 'attendance' %}
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

{% if active_section == 'events' %}
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

{% if active_section == 'declines' %}
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
p.write_text(prefix+combined+suffix, encoding='utf-8')
