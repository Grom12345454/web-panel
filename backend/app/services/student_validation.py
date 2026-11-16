"""Shared student identity validation for duplicate names and phone numbers."""
from __future__ import annotations

import unicodedata



def normalize_full_name(value: str | None) -> str:
    """Normalize name spelling for comparison without changing stored display text."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = " ".join(normalized.split()).casefold().replace("ё", "е")
    return normalized


def normalize_phone(value: str | None) -> str:
    """Compare phone numbers independent of spaces, punctuation and a leading 00."""
    digits = []
    for char in str(value or ""):
        if char.isdigit():
            try:
                digits.append(str(unicodedata.digit(char)))
            except (TypeError, ValueError):
                continue
    result = "".join(digits)
    if result.startswith("00"):
        result = result[2:]
    return result


def student_duplicate_message(
    full_name: str | None,
    phone: str | None,
    *,
    exclude_id: int | None = None,
    check_name: bool = True,
    check_phone: bool = True,
) -> str | None:
    """Return a user-safe validation message if another student has duplicate data.

    This deliberately compares normalized values in Python. The local test build uses
    SQLite and may contain older rows that were saved with inconsistent spacing or
    phone punctuation; comparing normalized values catches those legacy variants too.
    """
    # Import only when database-backed validation is requested. The normalizers stay
    # usable in lightweight tests and other code that does not initialize Flask.
    from database import Student

    name_key = normalize_full_name(full_name) if check_name else ""
    phone_key = normalize_phone(phone) if check_phone else ""
    if not name_key and not phone_key:
        return None

    query = Student.query.with_entities(Student.id, Student.full_name, Student.phone)
    if exclude_id is not None:
        query = query.filter(Student.id != exclude_id)

    duplicate_name = False
    duplicate_phone = False
    for student_id, existing_name, existing_phone in query.all():
        if name_key and normalize_full_name(existing_name) == name_key:
            duplicate_name = True
        if phone_key and normalize_phone(existing_phone) == phone_key:
            duplicate_phone = True
        if duplicate_name and duplicate_phone:
            break

    errors = []
    if duplicate_name:
        errors.append("Студент с таким ФИО уже зарегистрирован.")
    if duplicate_phone:
        errors.append("Этот номер телефона уже зарегистрирован.")
    return " ".join(errors) or None
