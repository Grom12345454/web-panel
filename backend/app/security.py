"""Route-scoped rate limits for Student App, bot ingress and panel authentication.

There are no app-wide defaults: public APIs and authentication endpoints receive
purpose-specific limits, while authenticated internal pages remain unaffected.
Use Redis for coordinated counters across multiple workers; the in-process
Student App guard and web-panel login/OTP checks remain as an outage fallback.
"""
from __future__ import annotations

import os


def _limit_from_env(name: str, default: str, legacy_defaults: tuple[str, ...] = ()) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or value.lower() in {item.lower() for item in legacy_defaults}:
        return default
    return value


def install_route_rate_limits(app, logger=None) -> bool:
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
    except ImportError:
        if logger:
            logger.warning(
                "Flask-Limiter missing; in-process Student App and admin login/OTP guards remain active"
            )
        return False

    # Keep the legacy read-limit variable for existing deployments. Writes now
    # have their own smaller bucket; reads stay generous for shared campus NATs.
    legacy_api_limit = _limit_from_env(
        "APP_STUDENT_API_RATE_LIMIT", "1800 per minute", legacy_defaults=("600 per minute",)
    )
    api_read_limit = _limit_from_env("APP_STUDENT_API_READ_RATE_LIMIT", legacy_api_limit)
    api_write_limit = _limit_from_env("APP_STUDENT_API_WRITE_RATE_LIMIT", "180 per minute")
    webhook_limit = _limit_from_env(
        "APP_BOT_WEBHOOK_RATE_LIMIT", "300 per minute", legacy_defaults=("240 per minute",)
    )
    admin_login_limit = _limit_from_env("APP_ADMIN_LOGIN_RATE_LIMIT", "30 per 15 minutes")
    admin_otp_limit = _limit_from_env("APP_ADMIN_OTP_RATE_LIMIT", "18 per 15 minutes")

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        storage_uri=(os.getenv("RATELIMIT_STORAGE_URI") or "memory://").strip(),
        default_limits=[],
        headers_enabled=True,
        strategy="fixed-window",
        # A storage outage must not take down the portal; bounded in-process
        # guards remain active for Mini App writes, password failures and OTP.
        swallow_errors=True,
    )

    route_methods: dict[str, set[str]] = {}
    route_paths: dict[str, set[str]] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint not in app.view_functions:
            continue
        route_methods.setdefault(rule.endpoint, set()).update(rule.methods or ())
        route_paths.setdefault(rule.endpoint, set()).add(rule.rule)

    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    read_methods = {"GET", "HEAD"}
    wrapped = set()
    for endpoint, paths in route_paths.items():
        methods = route_methods.get(endpoint, set())
        view = app.view_functions[endpoint]
        if any(path.startswith("/student-app/api/") for path in paths):
            # Flask-Limiter's method filters preserve distinct read/write budgets
            # even when one Flask view supports more than one HTTP method.
            if methods & read_methods:
                view = limiter.limit(api_read_limit, methods=sorted(methods & read_methods))(view)
            if methods & write_methods:
                view = limiter.limit(api_write_limit, methods=sorted(methods & write_methods))(view)
            app.view_functions[endpoint] = view
            wrapped.add(endpoint)
        elif "/hooks/max" in paths and "POST" in methods:
            app.view_functions[endpoint] = limiter.limit(webhook_limit, methods=["POST"])(view)
            wrapped.add(endpoint)

    # Login and OTP endpoints are protected by in-process account/IP counters in
    # web_app.py as well. These distributed per-IP limits coordinate workers.
    auth_limits = {
        "auth.login": (admin_login_limit, ["POST"]),
        "auth.verify_otp": (admin_otp_limit, ["POST"]),
    }
    for endpoint, (limit_value, methods) in auth_limits.items():
        if endpoint not in app.view_functions or endpoint in wrapped:
            continue
        app.view_functions[endpoint] = limiter.limit(limit_value, methods=methods)(
            app.view_functions[endpoint]
        )
        wrapped.add(endpoint)

    app.extensions["student_council_rate_limiter"] = limiter
    if logger:
        logger.info(
            "Route-scoped rate limits installed: Student App read/write, MAX webhook and admin login/OTP"
        )
    return True
