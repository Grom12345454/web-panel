"""WSGI adapter for the Flask application.

Run from the repository root with: waitress-serve --call backend.wsgi:create_application
The former ``backend.wsgi:create_app`` factory remains a compatible alias.
Legacy deployments may continue to import ``web_app`` at the repository root.
"""
from services.runtime_supervisor import start_worker
from web_app import create_app as _create_flask_app, notification_worker


def create_application():
    application = _create_flask_app()
    # WSGI deployments also need the notification queue consumer. Registering
    # through the supervisor keeps health reporting consistent and idempotent.
    start_worker("web-notifications", notification_worker)
    return application


def create_app():
    """Backward-compatible WSGI factory; includes supervised worker startup."""
    return create_application()


# Conventional import for servers configured with ``backend.wsgi:app``.
app = create_application()
