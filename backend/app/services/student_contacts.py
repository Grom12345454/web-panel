"""Public, verified messenger contacts for staff student cards.

Reads only MessengerIdentity rows created by the account linking workflow.
Never treats a text field typed in the staff editor as a verified identity.
"""
import re
from database import MessengerIdentity


def public_student_contacts(student_ids):
    ids = sorted({int(value) for value in student_ids if value is not None})
    if not ids:
        return {}
    result = {sid: {} for sid in ids}
    rows = MessengerIdentity.query.filter(MessengerIdentity.student_id.in_(ids)).order_by(MessengerIdentity.id.desc()).all()
    for row in rows:
        platform = str(row.platform or '').lower()
        student = result.get(row.student_id)
        if student is None or platform not in ('vk', 'max') or platform in student:
            continue
        username = str(row.public_username or '').strip().lstrip('@')
        if platform == 'vk':
            external = str(row.external_user_id or '').strip()
            if not external.isdecimal():
                continue
            student[platform] = {'label': '@'+username if re.fullmatch(r'[\w.]{1,80}', username) else 'VK ID '+external,
                                 'url': 'https://vk.com/id'+external}
        else:
            # A MAX username is only shown when the API supplied it for this
            # authenticated identity; do not invent profile URLs or user names.
            public = username if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', username) else ''
            student[platform] = {'label': '@'+public if public else 'Аккаунт подтверждён', 'url': None}
    return result
