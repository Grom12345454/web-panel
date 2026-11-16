"""Compatibility entry point; bot implementation lives in backend/app/bot.py."""
from pathlib import Path as _Path
_SOURCE = _Path(__file__).resolve().parent / "backend" / "app" / "bot.py"
__file__ = str(_SOURCE)
exec(compile(_SOURCE.read_text(encoding="utf-8"), __file__, "exec"), globals())
