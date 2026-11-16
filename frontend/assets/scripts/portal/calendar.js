/* Unified calendar UI: accessible month and agenda views, filters and contextual actions. */
(() => {
  'use strict';
  const root = document.getElementById('staff-calendar');
  const dataNode = document.getElementById('calendar-data');
  if (!root || !dataNode) return;
  let events = [];
  try { events = JSON.parse(dataNode.textContent || '[]'); } catch (_) { events = []; }
  const $ = (selector) => root.querySelector(selector);
  const now = new Date();
  const dateKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const fromKey = (key) => { const [year, month, day] = String(key || '').slice(0, 10).split('-').map(Number); return new Date(year || now.getFullYear(), (month || 1) - 1, day || 1, 12, 0, 0, 0); };
  const eventDate = (event) => String(event.start || '').slice(0, 10);
  const monthStart = (date) => new Date(date.getFullYear(), date.getMonth(), 1, 12);
  const monthEndExclusive = (date) => new Date(date.getFullYear(), date.getMonth() + 1, 1, 12);
  const monthTitle = (date) => new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' }).format(date);
  const longDate = (key) => new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(fromKey(key));
  const capitalise = (value) => value ? value[0].toLocaleUpperCase('ru-RU') + value.slice(1) : value;
  const timePart = (value) => { const match = String(value || '').match(/T(\d{2}:\d{2})/); return match ? match[1] : ''; };
  const timeLabel = (event) => { if (event.allDay || !timePart(event.start)) return event.timeRange || 'Весь день'; const start = timePart(event.start); const end = timePart(event.end); return end ? `${start}–${end}` : start; };
  const typeLabel = (event) => event.type === 'lesson' ? 'Занятие' : (event.isAnnouncement ? 'Публикация в чаты' : 'Мероприятие');
  const make = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined && text !== null) node.textContent = String(text); return node; };
  const addMeta = (container, icon, text) => { if (!text) return; const row = make('div', 'calendar-detail-meta-row'); row.append(make('span', '', icon), make('span', '', text)); container.append(row); };
  const withCalendarDate = (href, date = selectedDay) => { if (!href) return href; const url = new URL(href, window.location.origin); if (url.origin === window.location.origin && url.searchParams.get('return_to') === 'calendar') url.searchParams.set('date', date); return `${url.pathname}${url.search}${url.hash}`; };
  const addActionLink = (container, label, href, variant = 'btn-soft') => { if (!href) return; const link = make('a', `btn ${variant}`, label); link.href = withCalendarDate(href); container.append(link); };
  const addActionForm = (container, label, href, danger = false, confirmText = '') => {
    if (!href) return;
    const form = make('form'); form.method = 'post'; form.action = href;
    if (confirmText) form.dataset.confirm = confirmText;
    const token = make('input'); token.type = 'hidden'; token.name = 'csrf_token'; token.value = root.dataset.csrfToken || '';
    const returnTo = make('input'); returnTo.type = 'hidden'; returnTo.name = 'return_to'; returnTo.value = 'calendar';
    const calendarDate = make('input'); calendarDate.type = 'hidden'; calendarDate.name = 'calendar_date'; calendarDate.value = selectedDay;
    const button = make('button', `btn ${danger ? 'btn-danger' : 'btn-primary'}`, label); button.type = 'submit';
    form.append(token, returnTo, calendarDate, button);
    form.addEventListener('submit', (event) => { if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) event.preventDefault(); });
    container.append(form);
  };
  const todayKey = dateKey(now);
  const requestedDate = /^\d{4}-\d{2}-\d{2}$/.test(root.dataset.initialDate || '') ? root.dataset.initialDate : todayKey;
  let currentMonth = monthStart(fromKey(requestedDate)), selectedDay = requestedDate, selectedEventId = '', view = 'month', activeEvents = [];
  const search = $('#calendar-search'), typeFilter = $('#calendar-type-filter'), directionFilter = $('#calendar-direction-filter');
  if (root.dataset.initialDirection) directionFilter.value = root.dataset.initialDirection;
  if (['lesson', 'event'].includes(root.dataset.initialKind)) typeFilter.value = root.dataset.initialKind;
  const monthGrid = $('#calendar-month-grid'), monthView = $('#calendar-month-view'), agendaView = $('#calendar-agenda-view'), agendaList = $('#calendar-agenda-list');
  const dayEventsNode = $('#calendar-day-events'), detailSection = $('#calendar-event-detail'), detailContent = $('#calendar-detail-content');
  const createLinks = [['[data-calendar-create-lesson]', 'lesson'], ['[data-calendar-create-lesson-side]', 'lesson'], ['[data-calendar-create-event]', 'event'], ['[data-calendar-create-event-side]', 'event']];

  function filteredEvents() {
    const term = (search.value || '').trim().toLocaleLowerCase('ru-RU'), type = typeFilter.value, direction = directionFilter.value;
    return events.filter((event) => {
      if (type !== 'all' && event.type !== type) return false;
      if (direction !== 'all') { const ids = Array.isArray(event.directionIds) ? event.directionIds.map(String) : [String(event.directionId || '')]; if (!ids.includes(direction)) return false; }
      if (term && ![event.title, event.direction, event.description, event.location, event.teacher].some((part) => String(part || '').toLocaleLowerCase('ru-RU').includes(term))) return false;
      return true;
    }).sort((a, b) => String(a.start).localeCompare(String(b.start)) || String(a.title).localeCompare(String(b.title), 'ru'));
  }
  function eventsInMonth(source = activeEvents) { const start = dateKey(monthStart(currentMonth)), end = dateKey(monthEndExclusive(currentMonth)); return source.filter((event) => eventDate(event) >= start && eventDate(event) < end); }
  function syncCreateLinks() {
    createLinks.forEach(([selector]) => { const link = $(selector); if (!link) return; const url = new URL(link.getAttribute('href'), window.location.origin); url.searchParams.set('date', selectedDay); url.searchParams.set('return_to', 'calendar'); link.href = `${url.pathname}${url.search}${url.hash}`; });
  }
  function updateSummary() { const inMonth = eventsInMonth(); const onDay = activeEvents.filter((event) => eventDate(event) === selectedDay); $('#calendar-count-day').textContent = String(onDay.length); $('#calendar-count-lessons').textContent = String(inMonth.filter((event) => event.type === 'lesson').length); $('#calendar-count-events').textContent = String(inMonth.filter((event) => event.type === 'event' && !event.isAnnouncement).length); }

  function renderMonth() {
    $('#calendar-month-title').textContent = capitalise(monthTitle(currentMonth)); monthGrid.replaceChildren();
    const first = monthStart(currentMonth), mondayOffset = (first.getDay() + 6) % 7;
    const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - mondayOffset, 12), byDate = new Map();
    activeEvents.forEach((event) => { const key = eventDate(event); if (!byDate.has(key)) byDate.set(key, []); byDate.get(key).push(event); });
    for (let index = 0; index < 42; index += 1) {
      const date = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index, 12), key = dateKey(date), dayItems = byDate.get(key) || [];
      const cell = make('button', 'calendar-day-cell'); cell.type = 'button'; cell.dataset.date = key; cell.setAttribute('role', 'gridcell'); cell.setAttribute('aria-pressed', key === selectedDay ? 'true' : 'false'); cell.setAttribute('aria-label', `${longDate(key)}, событий: ${dayItems.length}`);
      if (date.getMonth() !== currentMonth.getMonth()) cell.classList.add('is-outside'); if (key === todayKey) cell.classList.add('is-today'); if (key === selectedDay) cell.classList.add('is-selected');
      cell.append(make('span', 'calendar-day-number', date.getDate()));
      dayItems.slice(0, 3).forEach((event) => { const chip = make('span', `calendar-event-chip calendar-event-chip--${event.type}${event.isAnnouncement ? ' is-announcement' : ''}`, `${timePart(event.start) ? `${timePart(event.start)} ` : ''}${event.title}`); chip.dataset.eventId = event.id; cell.append(chip); });
      if (dayItems.length > 3) cell.append(make('span', 'calendar-more-events', `+ ещё ${dayItems.length - 3}`));
      cell.addEventListener('click', (click) => { const chip = click.target.closest('[data-event-id]'); if (date.getMonth() !== currentMonth.getMonth()) currentMonth = monthStart(date); selectedDay = key; selectedEventId = chip ? chip.dataset.eventId : ''; render(); });
      monthGrid.append(cell);
    }
  }
  function renderAgenda() {
    agendaList.replaceChildren(); const list = eventsInMonth();
    if (!list.length) { agendaList.append(make('div', 'calendar-no-results', 'В этом месяце нет событий по выбранным фильтрам. Попробуйте изменить поиск или тип.')); return; }
    const byDate = new Map(); list.forEach((event) => { const key = eventDate(event); if (!byDate.has(key)) byDate.set(key, []); byDate.get(key).push(event); });
    [...byDate.keys()].sort().forEach((key) => {
      const group = make('section', 'calendar-agenda-group'); group.append(make('h3', 'calendar-agenda-date', capitalise(longDate(key))));
      byDate.get(key).forEach((event) => { const row = make('button', `calendar-agenda-item${event.id === selectedEventId ? ' is-selected' : ''}${event.isAnnouncement ? ' is-announcement' : ''}`); row.type = 'button'; row.append(make('span', 'calendar-agenda-time', timeLabel(event)), make('span', `calendar-agenda-mark is-${event.type}`)); const copy = make('span', 'calendar-agenda-copy'); copy.append(make('strong', '', event.title), make('small', '', `${event.direction || 'Без направления'}${event.location ? ` · ${event.location}` : ''}`)); row.append(copy); row.addEventListener('click', () => { selectedDay = key; selectedEventId = event.id; render(); }); group.append(row); });
      agendaList.append(group);
    });
  }
  function renderDayEvents() {
    dayEventsNode.replaceChildren(); const list = activeEvents.filter((event) => eventDate(event) === selectedDay);
    $('#calendar-selected-date').textContent = capitalise(new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' }).format(fromKey(selectedDay)));
    const countLabel = list.length === 1 ? 'событие' : (list.length > 1 && list.length < 5 ? 'события' : 'событий');
    $('#calendar-day-subtitle').textContent = list.length ? `${list.length} ${countLabel} в выбранный день` : 'На выбранную дату пока ничего не запланировано.';
    if (!list.length) { const empty = make('div', 'calendar-empty-day'); empty.append(make('div', 'calendar-empty-icon', '◷'), make('strong', '', 'Свободный день'), make('div', '', 'Здесь появятся новые занятия и мероприятия после создания.')); dayEventsNode.append(empty); return; }
    list.forEach((event) => { const button = make('button', `calendar-day-event${event.id === selectedEventId ? ' is-selected' : ''}${event.isAnnouncement ? ' is-announcement' : ''}`); button.type = 'button'; const mark = make('span', `calendar-day-event-mark is-${event.type}`); const copy = make('span', 'calendar-day-event-copy'); copy.append(make('strong', '', event.title), make('small', '', `${timeLabel(event)} · ${event.direction || 'Без направления'}${event.location ? ` · ${event.location}` : ''}`)); button.append(mark, copy); button.addEventListener('click', () => { selectedEventId = event.id; render(); }); dayEventsNode.append(button); });
  }
  function renderEventDetail() {
    const event = activeEvents.find((item) => item.id === selectedEventId && eventDate(item) === selectedDay);
    if (!event) { detailSection.hidden = true; dayEventsNode.hidden = false; return; }
    detailSection.hidden = false; dayEventsNode.hidden = true; detailContent.replaceChildren();
    detailContent.append(make('span', `calendar-detail-type is-${event.type}`, `${event.type === 'lesson' ? '●' : '◆'} ${typeLabel(event)}`), make('h3', 'calendar-detail-title', event.title));
    const meta = make('div', 'calendar-detail-meta');
    addMeta(meta, '◷', `${capitalise(longDate(selectedDay))} · ${timeLabel(event)}`);
    addMeta(meta, '◈', event.direction || 'Направление не указано');
    if (event.isAnnouncement) {
      addMeta(meta, '◉', event.status || 'Автопубликация запланирована');
      addMeta(meta, '✉', `Будет отправлено в: ${event.chatSummary || 'Чаты не выбраны'}`);
    } else {
      if (event.location) addMeta(meta, '⌖', event.location);
      if (event.type === 'lesson') { addMeta(meta, '♙', event.teacher ? `Ответственный: ${event.teacher}` : 'Ответственный не указан'); addMeta(meta, '◴', event.duration ? `Продолжительность: ${event.duration} мин.` : 'Продолжительность не указана'); if (event.capacity) addMeta(meta, '◎', `Мест: ${event.capacity}`); }
      else { addMeta(meta, '◎', `Мест на эту дату: ${event.capacity || 0}`); addMeta(meta, '◉', event.status || 'Статус не указан'); addMeta(meta, '✉', `Чаты объявления: ${event.chatSummary || 'Чаты не выбраны'}`); }
    }
    detailContent.append(meta); if (event.description) detailContent.append(make('p', 'calendar-detail-description', event.description));
    const actions = make('div', 'calendar-detail-actions');
    if (event.type === 'lesson') { if (event.editUrl) addActionLink(actions, 'Изменить занятие', event.editUrl, 'btn-primary'); if (event.publishUrl) addActionForm(actions, 'Отправить в TG / VK / MAX', event.publishUrl, false, 'Опубликовать объявление в чатах направления?'); if (event.deleteUrl) addActionForm(actions, 'Удалить', event.deleteUrl, true, 'Удалить занятие из расписания?'); }
    else if (event.isAnnouncement) { if (event.publishUrl) addActionForm(actions, 'Отправить сейчас', event.publishUrl, false, 'Отправить карточку мероприятия немедленно в выбранные чаты вместо ожидания запланированного времени?'); }
    else { if (event.participantsUrl) addActionLink(actions, 'Участники и посещаемость', withCalendarDate(event.participantsUrl), 'btn-primary'); if (event.publishUrl) addActionForm(actions, 'Отправить в выбранные чаты', event.publishUrl, false, 'Повторно отправить карточку мероприятия только в назначенные ему чаты?'); if (event.closeUrl) addActionForm(actions, 'Закрыть мероприятие', event.closeUrl, true, 'Закрыть мероприятие и зафиксировать статистику посещаемости?'); }
    if (event.detailUrl && !(event.type === 'lesson' && event.editUrl)) addActionLink(actions, 'Открыть раздел', event.detailUrl);
    if (actions.childNodes.length) detailContent.append(actions);
  }
  function render() {
    activeEvents = filteredEvents(); renderMonth(); renderAgenda(); renderDayEvents(); renderEventDetail(); updateSummary(); syncCreateLinks();
    monthView.hidden = view !== 'month'; agendaView.hidden = view !== 'agenda';
    root.querySelectorAll('[data-calendar-view]').forEach((button) => { const active = button.dataset.calendarView === view; button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', active ? 'true' : 'false'); });
  }
  function moveMonth(delta) { currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + delta, 1, 12); selectedDay = dateKey(currentMonth); selectedEventId = ''; render(); }
  $('#calendar-prev').addEventListener('click', () => moveMonth(-1));
  $('#calendar-next').addEventListener('click', () => moveMonth(1));
  $('#calendar-today').addEventListener('click', () => { currentMonth = monthStart(now); selectedDay = todayKey; selectedEventId = ''; render(); });
  root.querySelectorAll('[data-calendar-view]').forEach((button) => button.addEventListener('click', () => { view = button.dataset.calendarView; render(); }));
  $('#calendar-back-to-day').addEventListener('click', () => { selectedEventId = ''; render(); });
  [search, typeFilter, directionFilter].forEach((element) => element.addEventListener(element === search ? 'input' : 'change', () => { selectedEventId = ''; render(); }));
  render();
})();
