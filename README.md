# Wireshark AI Admin v8

Production-oriented SOC dashboard for real JSONL network/security logs. `blocks.json` is not used.

## What changed

- Real log source via `LOG_FILE` environment variable.
- `log_ingest.py` can tail JSONL, syslog-like and access-log text files.
- Qwen2.5 integration through local Ollama (`qwen2.5:7b` by default).
- Rule-engine fallback when Qwen/Ollama is unavailable.
- Defensive firewall page with TCP/UDP port and protocol policy.
- Firewall uses nftables and supports **preview before apply**.
- Management SSH port is protected from accidental blocking.
- Anti-malware policy page with human-review gate.
- Production deployment: systemd + Nginx + optional HTTPS + optional Ollama.
- API mutations can be protected with `ADMIN_TOKEN`.
- No Node.js dependency; backend uses Python standard library.

## Local development

```bash
python3 log_generator.py -n 200 -i 0.1 --clear
DEMO_MODE=true python3 server.py
```

Open `http://127.0.0.1:8787`.

## Real logs

Point the application at a real JSONL file:

```bash
LOG_FILE=/var/log/wireshark-ai/security-events.jsonl ADMIN_TOKEN='change-me' python3 server.py
```

For a separate source such as Suricata/SIEM/nginx:

```bash
LOG_FILE=/var/log/wireshark-ai/security-events.jsonl \
python3 log_ingest.py /var/log/suricata/eve.json --follow
```

The dashboard reads `/api/logs`, so historical events come from the configured file rather than a hard-coded block list.

## Qwen2.5

Install Ollama separately, then:

```bash
./install_qwen.sh
```

Default model: `qwen2.5:7b`.

The AI page calls `/api/analysis`. The server sends a compact sample of recent real events to the local Ollama endpoint. If Ollama is down, the server returns a deterministic rule-engine analysis instead of inventing AI results.

## Production deployment

Debian/Ubuntu:

```bash
sudo DOMAIN=soc.example.com \
  LOG_SOURCE=/var/log/suricata/eve.json \
  ENABLE_TLS=1 \
  INSTALL_OLLAMA=1 \
  QWEN_MODEL=qwen2.5:7b \
  ./deploy.sh
```

The script creates:

- `/opt/wireshark-ai-admin`
- `wireshark-ai.service`
- optional `wireshark-ai-ingest.service`
- Nginx reverse proxy
- `/etc/wireshark-ai.env`
- generated admin token

Paste the generated token into **Settings → Admin token**.

## Firewall

Use **Firewall → PREVIEW** first. Then save the policy and press **APPLY**. The server invokes nftables only when explicitly requested by the administrator.

The policy is stored in `config/security.json`. It is intentionally not named `blocks.json` and is not a log substitute.

## Security notes

- Put the UI behind HTTPS and preferably a VPN/zero-trust gateway.
- Keep `ADMIN_TOKEN` private.
- Do not expose Ollama directly to the Internet.
- Review real log permissions before running the ingestion service.
- Keep the human review gate enabled for automated response.
- Test firewall changes on a console/out-of-band channel before applying them to a remote host.

## Ubuntu Server one-command deployment

For Ubuntu Server, use the included `install_ubuntu.sh` rather than running the installer from an arbitrary working directory.

Minimal:

```bash
sudo ./install_ubuntu.sh
```

With a real Suricata log and HTTPS:

```bash
sudo DOMAIN=soc.example.com \
  LOG_SOURCE=/var/log/suricata/eve.json \
  LOG_GROUP=adm \
  ENABLE_TLS=1 \
  INSTALL_OLLAMA=1 \
  QWEN_MODEL=qwen2.5:7b \
  ./install_ubuntu.sh
```

The script installs Python, Nginx, nftables, systemd units, a dedicated service account, the dashboard, optional real-log ingestion, optional Ollama/Qwen2.5, and optional Let's Encrypt TLS.

The application binds to `127.0.0.1`; Nginx is the public entry point. The generated admin token is printed once at the end and is also stored in `/etc/wireshark-ai.env` with mode 0600.
