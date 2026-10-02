#!/usr/bin/env python3
"""Generate rich demo network-security logs as JSONL.

The dashboard consumes logs/security-events.jsonl. No blocks.json is used.
Run directly to create a larger historical dataset, or let server.py generate
one event per second for the live stream.
"""
from __future__ import annotations

import argparse
import json
import random
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

LOG_DIR = Path(os.environ.get("LOG_DIR", str(Path(__file__).resolve().parent / "logs")))
LOG_FILE = Path(os.environ.get("LOG_FILE", str(LOG_DIR / "security-events.jsonl")))
_LOG_LOCK = Lock()

NORMAL = [
    ("142.250.185.14", "google.com", 443, "HTTPS"),
    ("151.101.1.69", "github.com", 443, "HTTPS"),
    ("104.16.132.229", "cloudflare.com", 443, "HTTPS"),
    ("13.107.42.14", "microsoft.com", 443, "HTTPS"),
    ("20.42.65.90", "azure.microsoft.com", 443, "HTTPS"),
    ("18.64.20.12", "aws.amazon.com", 443, "HTTPS"),
    ("104.18.24.25", "npmjs.com", 443, "HTTPS"),
    ("151.101.0.223", "pypi.org", 443, "HTTPS"),
    ("142.250.72.196", "youtube.com", 443, "QUIC"),
    ("157.240.241.17", "instagram.com", 443, "HTTPS"),
    ("52.114.128.25", "slack.com", 443, "HTTPS"),
    ("170.114.52.2", "zoom.us", 443, "HTTPS"),
    ("1.1.1.1", "cloudflare-dns.com", 53, "DNS"),
    ("8.8.8.8", "dns.google", 53, "DNS"),
    ("129.6.15.28", "time.nist.gov", 123, "NTP"),
    ("10.20.0.1", "gateway.local", 67, "DHCP"),
    ("10.20.4.12", "fileserver.local", 445, "SMB"),
    ("10.20.5.20", "mail.local", 993, "IMAPS"),
    ("10.20.5.20", "mail.local", 587, "SMTP"),
    ("10.20.6.15", "directory.local", 636, "LDAPS"),
    ("10.20.8.40", "broker.local", 8883, "MQTT"),
    ("10.20.9.31", "monitor.local", 443, "HTTPS"),
]

WARNING = [
    ("104.18.32.47", "legacy-api.example", 8080, "HTTP", "legacy API over non-standard port", "policy.port_anomaly"),
    ("172.217.20.46", "update-service.example", 8080, "HTTP", "unexpected update endpoint", "policy.untrusted_update"),
    ("198.51.100.21", "telemetry-edge.example", 8443, "HTTPS", "unknown telemetry endpoint", "behavior.unknown_service"),
    ("203.0.113.44", "partner-sftp.example", 22, "SFTP", "external file transfer", "policy.external_sftp"),
    ("203.0.113.55", "smtp-relay.example", 25, "SMTP", "external SMTP relay", "policy.smtp_relay"),
    ("198.51.100.72", "ldap-legacy.example", 389, "LDAP", "unencrypted directory traffic", "policy.legacy_ldap"),
    ("203.0.113.88", "remote-admin.example", 3389, "RDP", "external remote administration", "policy.external_rdp"),
    ("198.51.100.91", "mqtt-public.example", 1883, "MQTT", "unencrypted public broker", "policy.public_mqtt"),
    ("203.0.113.17", "webhook-partner.example", 80, "HTTP", "plain HTTP webhook", "policy.cleartext_http"),
    ("198.51.100.33", "ftp-partner.example", 21, "FTP", "legacy FTP session", "policy.legacy_ftp"),
]

THREATS = [
    ("45.33.32.156", "c2-beacon.example", 443, "HTTPS", "C2 beacon pattern", "threat.c2_beacon"),
    ("185.220.101.34", "miner-pool.example", 3333, "TCP", "cryptomining pool connection", "threat.crypto_mining"),
    ("203.0.113.201", "smb-probe.example", 445, "SMB", "SMB lateral-movement probe", "threat.smb_probe"),
    ("198.51.100.202", "ssh-bruteforce.example", 22, "SSH", "SSH authentication burst", "threat.ssh_bruteforce"),
    ("203.0.113.203", "dns-tunnel.example", 53, "DNS", "high-entropy DNS tunnel", "threat.dns_tunnel"),
    ("198.51.100.204", "ftp-upload.example", 21, "FTP", "suspicious outbound FTP upload", "threat.ftp_exfil"),
    ("203.0.113.205", "ldap-enum.example", 389, "LDAP", "directory enumeration", "threat.ldap_enum"),
    ("198.51.100.206", "rdp-scan.example", 3389, "RDP", "remote desktop scan", "threat.rdp_scan"),
    ("203.0.113.207", "smtp-abuse.example", 25, "SMTP", "outbound mail abuse pattern", "threat.smtp_abuse"),
    ("198.51.100.208", "telnet-probe.example", 23, "TELNET", "legacy service probe", "threat.telnet_probe"),
    ("203.0.113.209", "icmp-sweep.example", 0, "ICMP", "host discovery sweep", "threat.icmp_sweep"),
    ("198.51.100.210", "quic-anomaly.example", 443, "QUIC", "unusual QUIC handshake", "threat.quic_anomaly"),
]

USER_AGENTS = ["Chrome/140", "Firefox/143", "Edge/140", "curl/8.16", "python-httpx", "sensor-agent/4.2"]
COUNTRIES = ["DE", "NL", "US", "GB", "FR", "IE", "SE", "FI", "SG"]
SENSORS = ["edge-fw-01", "core-sensor-02", "dmz-sensor-01", "branch-sensor-03"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def block_key(packet: dict[str, Any]) -> str:
    return f"{packet.get('src', '')}->{packet.get('dst', '')}:{packet.get('port', '')}"


def _source_ip(rng: random.Random) -> str:
    return f"10.{rng.choice([10, 20, 30])}.{rng.randrange(1, 30)}.{rng.randrange(10, 240)}"


def _profile(rng: random.Random, level: str, item: tuple) -> dict[str, Any]:
    dst, domain, port, protocol, *extra = item
    if level == "safe":
        category, rule = "normal", "baseline.allowlisted_service"
    else:
        category, rule = ("suspicious", extra[1]) if level == "warn" else ("threat", extra[1])

    signature = extra[0] if extra else "normal service traffic"
    method = rng.choice(["GET", "POST", "CONNECT", "QUERY"]) if protocol in {"HTTP", "HTTPS", "QUIC"} else None
    packets = rng.randint(3, 1800) if level == "safe" else rng.randint(20, 9000)
    bytes_count = packets * rng.randint(48, 980)

    return {
        "time": now_iso(),
        "no": int(time.time() * 1000) % 1000000,
        "src": _source_ip(rng),
        "dst": dst,
        "domain": domain,
        "port": port,
        "protocol": protocol,
        "transport": "UDP" if protocol in {"DNS", "QUIC", "NTP", "DHCP", "MQTT"} else "TCP",
        "type": level,
        "severity": {"safe": "normal", "warn": "medium", "danger": "high"}[level],
        "category": category,
        "rule": rule,
        "signature": signature,
        "confidence": rng.randint(72, 99) if level != "safe" else rng.randint(88, 99),
        "action": "monitor" if level == "safe" else "alert",
        "sensor": rng.choice(SENSORS),
        "direction": "outbound",
        "country": rng.choice(COUNTRIES),
        "packets": packets,
        "bytes": bytes_count,
        "latencyMs": rng.randint(8, 240),
        "userAgent": rng.choice(USER_AGENTS) if method else None,
        "method": method,
        "tls": rng.choice(["TLS1.2", "TLS1.3"]) if protocol in {"HTTPS", "QUIC"} else None,
        "dnsType": rng.choice(["A", "AAAA", "TXT", "CNAME"]) if protocol == "DNS" else None,
    }


def generate_packet(rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random.Random()
    roll = rng.random()
    if roll < 0.22:
        return _profile(rng, "danger", rng.choice(THREATS))
    if roll < 0.48:
        return _profile(rng, "warn", rng.choice(WARNING))
    return _profile(rng, "safe", rng.choice(NORMAL))


def append_log(event: dict[str, Any], kind: str = "telemetry") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "time": now_iso(), **event}
    with _LOG_LOCK:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate_logs(count: int, interval: float, seed: int | None, clear: bool = False) -> None:
    rng = random.Random(seed)
    if clear and LOG_FILE.exists():
        LOG_FILE.unlink()
    for _ in range(max(0, count)):
        packet = generate_packet(rng)
        append_log(packet)
        print(json.dumps(packet, ensure_ascii=False))
        if interval > 0:
            time.sleep(interval)
    print(f"Wrote logs to {LOG_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate rich Wireshark AI JSONL logs")
    parser.add_argument("-n", "--count", type=int, default=100)
    parser.add_argument("-i", "--interval", type=float, default=0)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--clear", action="store_true", help="replace the existing JSONL log")
    args = parser.parse_args()
    generate_logs(args.count, args.interval, args.seed, args.clear)


if __name__ == "__main__":
    main()
