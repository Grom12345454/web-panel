from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

STATE = Path(__file__).resolve().parent / "config" / "security.json"

ALLOWED_PROTOCOLS = {"tcp", "udp", "icmp", "icmpv6", "sctp", "gre", "esp", "ah", "telnet"}


def load_config() -> dict[str, Any]:
    if not STATE.exists():
        return {"firewall": {"enabled": False, "block_tcp_ports": [], "block_udp_ports": [], "block_protocols": [], "management_ssh_port": 22}}
    return json.loads(STATE.read_text(encoding="utf-8"))


def validate(policy: dict[str, Any]) -> list[str]:
    errors = []
    ssh = int(policy.get("management_ssh_port", 22))
    tcp = {int(x) for x in policy.get("block_tcp_ports", [])}
    udp = {int(x) for x in policy.get("block_udp_ports", [])}
    if ssh in tcp:
        errors.append(f"Refusing to block management SSH port {ssh}.")
    for port in tcp | udp:
        if not 1 <= port <= 65535:
            errors.append(f"Invalid port: {port}")
    for proto in policy.get("block_protocols", []):
        if str(proto).lower() not in ALLOWED_PROTOCOLS:
            errors.append(f"Unsupported protocol: {proto}")
    return errors


def render_rules(policy: dict[str, Any]) -> str:
    errors = validate(policy)
    if errors:
        raise ValueError(" ".join(errors))
    tcp = sorted({int(x) for x in policy.get("block_tcp_ports", [])})
    udp = sorted({int(x) for x in policy.get("block_udp_ports", [])})
    protos = [str(x).lower() for x in policy.get("block_protocols", [])]
    lines = ["table inet wireshark_ai {", " chain input_guard {", "  type filter hook input priority -20;", "  policy accept;", "  ct state established,related accept;", "  iifname \"lo\" accept;"]
    if tcp:
        lines.append("  tcp dport { " + ", ".join(map(str, tcp)) + " } drop;")
    if udp:
        lines.append("  udp dport { " + ", ".join(map(str, udp)) + " } drop;")
    for proto in protos:
        if proto == "icmp":
            lines.append("  ip protocol icmp drop;")
        elif proto == "icmpv6":
            lines.append("  ip6 nexthdr icmpv6 drop;")
        elif proto in {"tcp", "udp", "sctp", "gre", "esp", "ah"}:
            lines.append(f"  ip protocol {proto} drop;")
        elif proto == "telnet":
            lines.append("  tcp dport 23 drop;")
    lines.append(" }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def apply(policy: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    rules = render_rules(policy)
    if dry_run:
        return {"ok": True, "dryRun": True, "rules": rules}
    nft = shutil.which("nft")
    if not nft:
        return {"ok": False, "error": "nft command is not installed", "rules": rules}
    proc = subprocess.run([nft, "-f", "-"], input=rules.encode(), capture_output=True)
    return {"ok": proc.returncode == 0, "dryRun": False, "rules": rules, "stderr": proc.stderr.decode(errors="replace")}
