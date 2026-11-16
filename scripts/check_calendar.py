"""Read-only troubleshooting for the Galaxy calendar and chat publication.

Run from project root: python scripts/check_calendar.py
Does not print tokens, chat IDs, student details or message bodies.
"""
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
import argparse
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, func
from web_app import create_app
from database import db, Lesson, EventQuota, EventDay, DirectionChat, MessengerChat, BotDeliveryJob

parser = argparse.ArgumentParser(description='Безопасная диагностика календаря и доставки')
parser.add_argument('--event', type=int, help='ID мероприятия для диагностики очереди')
parser.add_argument('--lesson', type=int, help='ID занятия для диагностики очереди')
args = parser.parse_args()
app = create_app()
missing = []
with app.app_context():
    requirements = {
        'events': ('event_quotas', 'event_days', 'quota_directions'),
        'lessons': ('lessons',),
        'people': ('directions', 'direction_chats'),
        'system': ('messenger_chats', 'bot_delivery_jobs'),
    }
    print('Проверка таблиц Galaxy Mission Control:')
    for bind, expected in requirements.items():
        engine = db.engines[None if bind == 'people' else bind]
        found = set(inspect(engine).get_table_names())
        absent = [name for name in expected if name not in found]
        missing.extend(f'{bind}.{name}' for name in absent)
        print(f'  {bind}: ' + ('OK' if not absent else 'НЕТ ТАБЛИЦ: ' + ', '.join(absent)))
    if not missing:
        print('\nСводка без персональных данных:')
        for label, model in [('Занятия', Lesson), ('Мероприятия', EventQuota),
                             ('Даты мероприятий', EventDay), ('Telegram-чаты', DirectionChat),
                             ('VK/MAX-чаты', MessengerChat)]:
            print(f'  {label}: {model.query.count()}')
        for status in ('pending', 'blocked', 'retry', 'sending', 'delivered', 'failed'):
            print(f'  Публикации ({status}): {BotDeliveryJob.query.filter_by(status=status).count()}')
        if args.event or args.lesson:
            source_type, source_id = ('event', args.event) if args.event else ('lesson', args.lesson)
            jobs = BotDeliveryJob.query.filter_by(source_type=source_type, source_id=source_id).all()
            print(f'\nПубликация {source_type} #{source_id}: {len(jobs)} записей доставки')
            for (platform, status), count in sorted(Counter((j.platform, j.status) for j in jobs).items()):
                print(f'  {platform}: {status} — {count}')
            if not jobs:
                print('  Нет заданий: убедитесь, что событие опубликовано и выбранные направления имеют активные чаты.')
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        stalled = BotDeliveryJob.query.filter(
            BotDeliveryJob.status.in_(['pending', 'sending', 'retry']),
            BotDeliveryJob.next_attempt_at < cutoff,
        ).count()
        if stalled:
            print(f'\nВНИМАНИЕ: {stalled} заданий ожидают давно. Проверьте запуск единственного фонового обработчика.')
        print('\nПри ошибке 500 найдите в серверном журнале строку '
              '"Unhandled web error request_id=..." с кодом обращения, затем traceback.')
    else:
        print('\nОбнаружены отсутствующие таблицы. Перед запуском сохраните резервную копию базы, '
              'затем запустите python run.py для создания/обновления схемы.')
        raise SystemExit(1)
