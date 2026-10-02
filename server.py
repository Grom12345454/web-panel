#!/usr/bin/env python3
"""Wireshark AI Admin production-friendly stdlib server.

- Reads real JSONL telemetry from LOG_FILE (no blocks.json).
- Optional demo generator can be enabled with DEMO_MODE=true.
- Qwen2.5 analysis is provided through local Ollama.
- Firewall policy is stored in config/security.json and can be dry-run/applied.
- API mutations require ADMIN_TOKEN when set.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ai_analyzer import analyze
from firewall import apply as apply_firewall, load_config
from log_generator import LOG_FILE, append_log, block_key, generate_packet

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))
PUBLIC = Path(__file__).resolve().parent / "public"
CONFIG_FILE = Path(__file__).resolve().parent / "config" / "security.json"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() in {"1", "true", "yes"}

_clients: set[BaseHTTPRequestHandler] = set()
_clients_lock = threading.Lock()
_blocks: dict[str, dict] = {}
_blocks_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_config() -> dict:
    if not CONFIG_FILE.exists():
        return load_config()
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return load_config()


def write_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(CONFIG_FILE)


def register_block(packet: dict, reason: str) -> dict:
    key = block_key(packet)
    with _blocks_lock:
        existing = _blocks.get(key)
        if existing:
            return existing
        entry = {
            "key": key,
            "src": packet.get("src"),
            "dst": packet.get("dst"),
            "domain": packet.get("domain"),
            "port": packet.get("port"),
            "type": packet.get("type"),
            "reason": reason,
            "created": now_iso(),
            "status": "blocked",
            "admin_unlock": packet.get("type") == "warn",
        }
        _blocks[key] = entry
    append_log({"action": "block", "block": entry}, kind="security-action")
    return entry


def packet() -> dict:
    result = generate_packet()
    if result["type"] in {"danger", "warn"}:
        entry = register_block(result, "automatic policy: critical threat" if result["type"] == "danger" else "automatic policy: suspicious activity")
        result.update({"blocked": entry["status"] == "blocked", "blockKey": entry["key"], "blockPolicy": "permanent" if result["type"] == "danger" else "admin-unlock"})
    else:
        result["blocked"] = False
    append_log(result)
    return result


def sse(data: dict) -> bytes:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def add_client(handler: BaseHTTPRequestHandler) -> None:
    with _clients_lock:
        _clients.add(handler)


def remove_client(handler: BaseHTTPRequestHandler) -> None:
    with _clients_lock:
        _clients.discard(handler)


def broadcast(data: dict) -> None:
    message = sse(data)
    with _clients_lock:
        clients = list(_clients)
    dead = []
    for client in clients:
        try:
            client.wfile.write(message)
            client.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            dead.append(client)
    for client in dead:
        remove_client(client)


def recent_logs(limit: int = 100) -> list[dict]:
    logs = []
    if LOG_FILE.is_file():
        try:
            with LOG_FILE.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle.readlines()[-limit:]:
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
    return logs


class Handler(BaseHTTPRequestHandler):
    server_version = "WiresharkAI/4.0"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            pass

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")

    def authorized(self, mutation: bool = False) -> bool:
        if not ADMIN_TOKEN:
            return True
        supplied = self.headers.get("X-Admin-Token", "")
        if supplied and secrets.compare_digest(supplied, ADMIN_TOKEN):
            return True
        return not mutation and urlparse(self.path).path in {"/api/health", "/api/logs", "/api/config", "/events"}

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(min(length, 1_000_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json({"ok": False, "error": "Invalid JSON"}, 400)
            return None

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self.authorized(mutation=True):
            self.send_json({"ok": False, "error": "Unauthorized"}, 401)
            return
        payload = self.read_json()
        if payload is None:
            return

        if path in {"/api/block", "/api/unblock"}:
            key = str(payload.get("key", ""))
            if not key:
                self.send_json({"ok": False, "error": "Block key is required"}, 400)
                return
            with _blocks_lock:
                entry = _blocks.get(key)
                if not entry:
                    self.send_json({"ok": False, "error": "Block not found"}, 404)
                    return
                if path == "/api/unblock":
                    if entry.get("type") != "warn" or not entry.get("admin_unlock"):
                        self.send_json({"ok": False, "error": "Critical blocks cannot be unlocked"}, 403)
                        return
                    entry["status"] = "unblocked"
                    entry["unblocked"] = now_iso()
                    entry["unblockedBy"] = "admin"
                    action = "unblock"
                else:
                    action = "block"
                result = dict(entry)
            append_log({"action": action, "block": result}, kind="security-action")
            self.send_json({"ok": True, "action": action, "entry": result})
            return

        if path == "/api/config":
            current = read_config()
            for section in ("ai", "security", "firewall"):
                if isinstance(payload.get(section), dict):
                    current.setdefault(section, {}).update(payload[section])
            write_config(current)
            self.send_json({"ok": True, "config": current})
            return

        if path == "/api/firewall/apply":
            config = read_config()
            dry_run = bool(payload.get("dryRun", True))
            result = apply_firewall(config.get("firewall", {}), dry_run=dry_run)
            if result.get("ok"):
                append_log({"action": "firewall_apply", "dryRun": dry_run, "rules": result.get("rules", "")}, kind="security-action")
            self.send_json(result, 200 if result.get("ok") else 500)
            return

        if path == "/api/ingest":
            event = payload.get("event", payload)
            if not isinstance(event, dict):
                self.send_json({"ok": False, "error": "event must be an object"}, 400)
                return
            append_log(event, kind="ingested")
            broadcast({"event": "packet", "data": event})
            self.send_json({"ok": True, "event": event})
            return

        self.send_json({"ok": False, "error": "Not found"}, 404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/events":
            if not self.authorized(False):
                self.send_json({"ok": False, "error": "Unauthorized"}, 401)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(sse({"event": "connected", "time": now_iso()}))
                self.wfile.flush()
                add_client(self)
                while True:
                    time.sleep(30)
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                remove_client(self)
            return

        if path == "/api/blocks":
            if not self.authorized(False):
                self.send_json({"ok": False, "error": "Unauthorized"}, 401)
                return
            with _blocks_lock:
                blocks = list(_blocks.values())
            self.send_json({"ok": True, "blocks": blocks})
            return

        if path == "/api/logs":
            try:
                limit = min(max(int(parse_qs(parsed.query).get("limit", ["100"])[0]), 1), 2000)
            except ValueError:
                limit = 100
            self.send_json({"ok": True, "logs": recent_logs(limit), "source": str(LOG_FILE), "demo": DEMO_MODE})
            return

        if path == "/api/analysis":
            logs = recent_logs(40)
            config = read_config().get("ai", {})
            result = analyze(logs, url=config.get("url", "http://127.0.0.1:11434/api/generate"), model=config.get("model", "qwen2.5:7b"), timeout=int(config.get("timeout_seconds", 30)))
            self.send_json({"ok": True, "analysis": result})
            return

        if path == "/api/config":
            self.send_json({"ok": True, "config": read_config()})
            return

        if path == "/api/firewall/preview":
            result = apply_firewall(read_config().get("firewall", {}), dry_run=True)
            self.send_json(result, 200 if result.get("ok") else 400)
            return

        if path == "/api/health":
            with _clients_lock:
                clients = len(_clients)
            self.send_json({"ok": True, "time": now_iso(), "clients": clients, "mode": "demo" if DEMO_MODE else "production", "logFile": str(LOG_FILE)})
            return

        if path == "/api/packet":
            if not DEMO_MODE:
                self.send_json({"ok": False, "error": "Demo telemetry is disabled"}, 403)
                return
            self.send_json(packet())
            return

        requested = "/index.html" if path in {"", "/"} else path
        candidate = (PUBLIC / requested.lstrip("/")).resolve()
        try:
            candidate.relative_to(PUBLIC.resolve())
        except ValueError:
            self.send_error(404, "Not found")
            return
        if not candidate.is_file():
            self.send_error(404, "Not found")
            return
        content_type, _ = mimetypes.guess_type(str(candidate))
        content_type = content_type or "application/octet-stream"
        if candidate.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif candidate.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif candidate.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        try:
            data = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500, "Unable to read file")


def telemetry_loop() -> None:
    while DEMO_MODE:
        time.sleep(1)
        broadcast({"event": "packet", "data": packet()})


def main() -> None:
    if not PUBLIC.is_dir():
        raise SystemExit(f"Public directory not found: {PUBLIC}")
    if DEMO_MODE:
        threading.Thread(target=telemetry_loop, daemon=True, name="demo-telemetry").start()
    class QuietThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        def handle_error(self, request, client_address) -> None:
            exc = __import__("sys").exc_info()[1]
            if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout, OSError)):
                return
            super().handle_error(request, client_address)
    server = QuietThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Wireshark AI Admin: http://{HOST}:{PORT}")
    print(f"Mode: {'DEMO' if DEMO_MODE else 'PRODUCTION'} | logs: {LOG_FILE}")
    if ADMIN_TOKEN:
        print("API mutations: token protected")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
