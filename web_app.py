"""Compatibility entry point; Flask application lives in backend/app/web_app.py."""
from pathlib import Path as _Path
_SOURCE = _Path(__file__).resolve().parent / "backend" / "app" / "web_app.py"
__file__ = str(_SOURCE)
exec(compile(_SOURCE.read_text(encoding="utf-8"), __file__, "exec"), globals())
