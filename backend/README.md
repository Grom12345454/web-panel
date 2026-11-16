# Backend architecture

Canonical Python implementation is inside `backend/app/`. Root-level `run.py`, `main.py`, `web_app.py`, `config.py`, `bot.py`, `bot_messages.py`, `security.py`, and the `database/`, `handlers/`, `services/` packages are compatibility entrypoints for older Windows launchers, scripts and integrations. New implementation belongs under `backend/app/`; do not add new domain logic to the root adapters.

## Layers

- `web_app.py`: Flask application factory, route registration, request lifecycle and HTTP boundary.
- `services/`: business/domain logic, authorization policy, Telegram/VK/MAX transports, outbox and supervised workers.
- `database/`: ORM models, database bindings, persistence helpers and schema initialization.
- `handlers/`: Telegram routers/handlers only; handlers call services rather than embedding business rules.
- `config.py`: environment loading and canonical `BASE_DIR`/`DATA_DIR` paths.
- `security.py`: rate limiting and web security integration.

## Dependency direction

`HTTP routes / bot handlers -> services -> database`. Services may use configuration and domain adapters; database modules must not import Flask routes or transport handlers. Keep network calls outside database model modules. Background work must be registered through `services/runtime_supervisor.py`.

## Compatibility

Root import facades preserve current import names (`from database import db`, `from services.foo import bar`, `from handlers.foo import router`, `from web_app import create_app`). New code should import through the same stable top-level facade only where a cross-domain dependency is necessary; within the backend prefer domain-level imports and avoid cycles. Compatibility facades are intentionally tiny and should not contain business logic.

## Run

```powershell
python run.py
```

Production WSGI factory: `backend.wsgi:create_application` (configure the WSGI server with the project root as its working directory).
