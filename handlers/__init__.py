"""Backward-compatible import facade; implementation lives in backend/app/handlers."""
from pathlib import Path as _Path
__path__ = [str(_Path(__file__).resolve().parents[1] / "backend" / "app" / "handlers")]
