"""Backward-compatible import facade; implementation lives in backend/app/services."""
from pathlib import Path as _Path
__path__ = [str(_Path(__file__).resolve().parents[1] / "backend" / "app" / "services")]
