# Application source package

This folder contains the canonical Python implementation. Use the root-level compatibility adapters for legacy imports, while keeping implementation changes here.

- `web_app.py` — Flask routes, app factory, sessions, API boundary.
- `config.py` — settings and canonical repository/data paths.
- `security.py` — public endpoint rate limiting.
- `database/` — persistence models and database operations.
- `services/` — domain logic and integrations.
- `handlers/` — Telegram update handlers.

The legacy package names `database`, `services`, and `handlers` are mapped to these source directories by root adapters so the current runtime and installed deployments continue to work.
