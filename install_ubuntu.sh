#!/usr/bin/env bash
set -Eeuo pipefail

# Ubuntu Server installer for Wireshark AI Admin v8.
# Usage examples:
#   sudo DOMAIN=soc.example.com ./install_ubuntu.sh
#   sudo DOMAIN=soc.example.com LOG_SOURCE=/var/log/suricata/eve.json ENABLE_TLS=1 INSTALL_OLLAMA=1 ./install_ubuntu.sh
#
# Supported: Ubuntu 22.04 LTS / 24.04 LTS (and newer Ubuntu releases with systemd).

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo ./install_ubuntu.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/opt/wireshark-ai-admin}"
SERVICE_USER="${SERVICE_USER:-wiresharkai}"
SERVICE_GROUP="${SERVICE_GROUP:-wiresharkai}"
PORT="${PORT:-8787}"
DOMAIN="${DOMAIN:-_}"
LOG_FILE="${LOG_FILE:-/var/lib/wireshark-ai/security-events.jsonl}"
LOG_SOURCE="${LOG_SOURCE:-}"
LOG_GROUP="${LOG_GROUP:-}"
INSTALL_OLLAMA="${INSTALL_OLLAMA:-0}"
QWEN_MODEL="${QWEN_MODEL:-qwen2.5:7b}"
ENABLE_TLS="${ENABLE_TLS:-0}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
SSH_PORT="${SSH_PORT:-22}"

export DEBIAN_FRONTEND=noninteractive

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "$SCRIPT_DIR/server.py" ]] || fail "Run this script from the project directory (server.py not found)."

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
else
  fail "Cannot detect operating system."
fi
[[ "${ID:-}" == "ubuntu" ]] || fail "This installer targets Ubuntu Server. Detected: ${ID:-unknown}."

log "Installing Ubuntu packages"
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-venv nginx nftables curl ca-certificates rsync openssl \
  logrotate

if [[ -n "$LOG_SOURCE" && ! -e "$LOG_SOURCE" ]]; then
  echo "WARNING: LOG_SOURCE does not exist yet: $LOG_SOURCE" >&2
  echo "The ingestion service will retry after the file appears."
fi

log "Creating service account"
if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Optional group for common log files such as root:adm 0640.
if [[ -n "$LOG_GROUP" ]] && getent group "$LOG_GROUP" >/dev/null; then
  usermod -aG "$LOG_GROUP" "$SERVICE_USER"
fi

log "Installing application to $APP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$APP_DIR"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='logs/security-events.jsonl' \
  "$SCRIPT_DIR/" "$APP_DIR/"

install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
  "$APP_DIR/logs" "$APP_DIR/config" "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_FILE"

# Initialize configuration if missing.
if [[ ! -f "$APP_DIR/config/security.json" ]]; then
  if [[ -f "$APP_DIR/config.example.json" ]]; then
    cp "$APP_DIR/config.example.json" "$APP_DIR/config/security.json"
  else
    cat > "$APP_DIR/config/security.json" <<JSON
{
  "firewall": {
    "enabled": false,
    "block_tcp_ports": [],
    "block_udp_ports": [],
    "block_protocols": [],
    "management_ssh_port": $SSH_PORT
  },
  "malware": {
    "monitoring": true,
    "auto_quarantine": false,
    "human_review": true
  }
}
JSON
  fi
fi
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR/config" "$APP_DIR/logs"

if [[ -z "$ADMIN_TOKEN" ]]; then
  ADMIN_TOKEN="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9_-' | head -c 48)"
fi

# Restrict the application to localhost. Nginx is the public entry point.
cat > /etc/wireshark-ai.env <<ENV
HOST=127.0.0.1
PORT=$PORT
LOG_FILE=$LOG_FILE
ADMIN_TOKEN=$ADMIN_TOKEN
DEMO_MODE=false
QWEN_MODEL=$QWEN_MODEL
QWEN_URL=http://127.0.0.1:11434/api/generate
ENV
chmod 600 /etc/wireshark-ai.env

log "Creating systemd service"
cat > /etc/systemd/system/wireshark-ai.service <<SERVICE
[Unit]
Description=Wireshark AI Admin v8
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/wireshark-ai.env
ExecStart=/usr/bin/python3 $APP_DIR/server.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths=$APP_DIR $LOG_FILE

[Install]
WantedBy=multi-user.target
SERVICE

if [[ -n "$LOG_SOURCE" ]]; then
  log "Creating real-log ingestion service"
  cat > /etc/systemd/system/wireshark-ai-ingest.service <<SERVICE
[Unit]
Description=Wireshark AI real log ingestion
After=wireshark-ai.service
Wants=wireshark-ai.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/wireshark-ai.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $APP_DIR/log_ingest.py $LOG_SOURCE --follow
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR $LOG_FILE

[Install]
WantedBy=multi-user.target
SERVICE
fi

log "Configuring Nginx"
cat > /etc/nginx/sites-available/wireshark-ai <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 2m;

    location /events {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        proxy_send_timeout 1h;
    }

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/wireshark-ai /etc/nginx/sites-enabled/wireshark-ai
rm -f /etc/nginx/sites-enabled/default
nginx -t

log "Enabling services"
systemctl daemon-reload
systemctl enable --now nftables
systemctl enable --now wireshark-ai
if [[ -n "$LOG_SOURCE" ]]; then
  systemctl enable --now wireshark-ai-ingest
fi
systemctl enable --now nginx
systemctl reload nginx

if [[ "$INSTALL_OLLAMA" == "1" ]]; then
  log "Installing Ollama"
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  systemctl enable --now ollama || true
  log "Pulling $QWEN_MODEL"
  ollama pull "$QWEN_MODEL"
fi

if [[ "$ENABLE_TLS" == "1" && "$DOMAIN" != "_" ]]; then
  log "Installing Certbot and requesting HTTPS certificate"
  apt-get install -y --no-install-recommends certbot python3-certbot-nginx
  certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email \
    -d "$DOMAIN" --redirect
  systemctl reload nginx
fi

# Basic local health check.
sleep 1
if curl -fsS "http://127.0.0.1:$PORT/api/health" >/tmp/wireshark-ai-health.json; then
  log "Application health check: OK"
else
  echo "WARNING: application health check failed. Check: journalctl -u wireshark-ai -n 100 --no-pager" >&2
fi
rm -f /tmp/wireshark-ai-health.json

cat <<SUMMARY

============================================================
 Wireshark AI Admin v8 - Ubuntu Server installation complete
============================================================

URL:          http://$DOMAIN/
App:          $APP_DIR
Service:      systemctl status wireshark-ai
Logs:         $LOG_FILE
Config:       $APP_DIR/config/security.json
Env:          /etc/wireshark-ai.env

Admin token:
$ADMIN_TOKEN

Use it in: Settings -> Admin token

Useful commands:
  systemctl status wireshark-ai
  journalctl -u wireshark-ai -f
$( [[ -n "$LOG_SOURCE" ]] && echo "  systemctl status wireshark-ai-ingest" )
$( [[ -n "$LOG_SOURCE" ]] && echo "  journalctl -u wireshark-ai-ingest -f" )

Firewall:
  Use Firewall -> PREVIEW before APPLY.
  Keep console/out-of-band access available on a remote server.

Qwen:
  Model: $QWEN_MODEL
  Ollama: http://127.0.0.1:11434

============================================================
SUMMARY
