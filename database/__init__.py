"""Backward-compatible import facade for the backend database package.

New source of truth: ``backend/app/database``.  This facade preserves imports such
as ``from database import User`` and ``from database.helpers import ...``.
"""
from pathlib import Path as _Path

_SOURCE = _Path(__file__).resolve().parents[1] / "backend" / "app" / "database"
__path__ = [str(_SOURCE)]
__file__ = str(_SOURCE / "__init__.py")
exec(compile((_SOURCE / "__init__.py").read_text(encoding="utf-8"), __file__, "exec"), globals())
