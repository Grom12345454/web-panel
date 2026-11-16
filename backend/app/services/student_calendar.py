"""Pure Student App calendar normalization shared by lessons and quota event days.

The calendar does not use chat announcements as a data source: publications to
Telegram/VK/MAX are independent of the entries saved in the lesson/event DBs.
"""
from datetime import date, datetime


def _calendar_date(value):
    """Return YYYY-MM-DD for the two supported persisted date representations."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def combine_calendar_items(lessons, events):
    """Combine and deduplicate persisted lessons and published event occurrences.

    An entry is included independently of whether a chat announcement was sent.
    This function is deliberately framework- and database-independent.
    """
    items, seen = [], set()
    for lesson in lessons or []:
        when = _calendar_date(lesson.get('date'))
        if not when:
            continue
        key = ('lesson', lesson.get('id'), when)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            'kind': 'lesson', 'id': lesson.get('id'), 'date': when,
            'direction_id': lesson.get('direction_id'),
            'time': lesson.get('time') or '00:00', 'title': lesson.get('title') or 'Занятие',
            'direction_name': lesson.get('direction_name') or '',
            'description': lesson.get('description') or '', 'room': lesson.get('room') or '',
            'teacher': lesson.get('teacher') or '', 'end_time': lesson.get('end_time') or '',
            'duration_minutes': lesson.get('duration_minutes') or 90,
        })
    for event in events or []:
        for day in event.get('days', []):
            when = _calendar_date(day.get('date'))
            if not when:
                continue
            key = ('event', event.get('id'), day.get('id'), when)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                'kind': 'event', 'id': day.get('id'), 'event_id': event.get('id'),
                'date': when, 'time': event.get('time') or '',
                'title': event.get('title') or 'Мероприятие',
                'description': event.get('description') or '',
                'room': event.get('location') or '',
                'direction_ids': event.get('direction_ids') or [],
                'registered': bool(day.get('registered')),
            })
    return sorted(items, key=lambda item: (item['date'], item['time'], item['kind'], item['id'] or 0))
