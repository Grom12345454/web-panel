#!/usr/bin/env bash
set -euo pipefail

# Production deployment for Debian/Ubuntu.
# Usage: sudo DOMAIN=soc.example.com LOG_SOURCE=/var/log/suricata/eve.json deploy.sh

APP_DIR="${APP_DIR:-/opt/wireshark-ai-admin}"
SERVICE_USER="${SERVICE_USER:-wiresharkai}"
PORT="${PORT:-8787}"
DOMAIN="${DOMAIN:-_}"
LOG_FILE="${LOG_FILE:-/var/lib/wireshark-ai/security-events.jsonl}"
LOG_SOURCE="${LOG_SOURCE:-}"
INSTALL_OLLAMA="${INSTALL_OLLAMA:-0}"
QWEN_MODEL="${QWEN_MODEL:-qwen2.5:7b}"
ENABLE_TLS="${ENABLE_TLS:-0}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

if [[ $EUID -ne 0 ]]; then echo "Run as root: sudo ./deploy.sh"; exit 1; fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 nginx curl ca-certificates rsync

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$APP_DIR" "$APP_DIR/logs" "$APP_DIR/config" "$(dirname "$LOG_FILE")"
rsync -a --delete --exclude='logs/security-events.jsonl' ./ "$APP_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
touch "$LOG_FILE"
chown "$SERVICE_USER:$SERVICE_USER" "$LOG_FILE" || true

if [[ -z "$ADMIN_TOKEN" ]]; then
  ADMIN_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
fi

cat > /etc/wireshark-ai.env <<EOF2
HOST=127.0.0.1
PORT=$PORT
LOG_FILE=$LOG_FILE
ADMIN_TOKEN=$ADMIN_TOKEN
DEMO_MODE=false
QWEN_MODEL=$QWEN_MODEL
QWEN_URL=http://127.0.0.1:11434/api/generate
EOF2
chmod 600 /etc/wireshark-ai.env

cat > /etc/systemd/system/wireshark-ai.service <<EOF2
[Unit]
Description=Wireshark AI Admin
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/wireshark-ai.env
ExecStart=/usr/bin/python3 $APP_DIR/server.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR $LOG_FILE

[Install]
WantedBy=multi-user.target
EOF2

if [[ -n "$LOG_SOURCE" ]]; then
  cat > /etc/systemd/system/wireshark-ai-ingest.service <<EOF2
[Unit]
Description=Wireshark AI real-log ingestion
After=wireshark-ai.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/wireshark-ai.env
ExecStart=/usr/bin/python3 $APP_DIR/log_ingest.py $LOG_SOURCE --follow
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR $LOG_FILE

[Install]
WantedBy=multi-user.target
EOF2
fi

cat > /etc/nginx/sites-available/wireshark-ai <<EOF2
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
    }

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF2
ln -sfn /etc/nginx/sites-available/wireshark-ai /etc/nginx/sites-enabled/wireshark-ai
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now wireshark-ai
[[ -n "$LOG_SOURCE" ]] && systemctl enable --now wireshark-ai-ingest || true
systemctl reload nginx

if [[ "$ENABLE_TLS" == "1" && "$DOMAIN" != "_" ]]; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx
  certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email -d "$DOMAIN" --redirect || true
  systemctl reload nginx
fi

if [[ "$INSTALL_OLLAMA" == "1" && ! -x "$(command -v ollama || true)" ]]; then
  echo "Installing Ollama from the official installer..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
if command -v ollama >/dev/null 2>&1; then
  systemctl enable --now ollama || true
  ollama pull "$QWEN_MODEL" || true
fi

cat <<EOF2

Deployment complete.
URL: http://$DOMAIN/
App: $APP_DIR
Logs: $LOG_FILE
Admin token: $ADMIN_TOKEN

Paste the token into Settings -> Admin token.
For Internet-facing use, put this behind HTTPS (for example certbot/nginx) and restrict access by VPN/firewall.
EOF2
