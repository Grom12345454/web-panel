#!/usr/bin/env python3
"""Tail a real JSONL/syslog/access log and normalize it into the dashboard JSONL store."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from log_generator import append_log

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PORT_RE = re.compile(r"(?:port|dport|dst_port)[=: ]+(\d{1,5})", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize(line: str, source: str) -> dict:
    line = line.rstrip("\n")
    try:
        item = json.loads(line)
        if isinstance(item, dict):
            item.setdefault("time", now_iso())
            item.setdefault("kind", "ingested")
            item.setdefault("source", source)
            return item
    except json.JSONDecodeError:
        pass

    ips = IP_RE.findall(line)
    port_match = PORT_RE.search(line)
    return {
        "time": now_iso(),
        "kind": "ingested",
        "source": source,
        "raw": line[:4000],
        "src": ips[0] if ips else None,
        "dst": ips[1] if len(ips) > 1 else None,
        "port": int(port_match.group(1)) if port_match else None,
        "protocol": "UNKNOWN",
        "type": "safe",
        "severity": "normal",
        "category": "raw-log",
        "rule": "ingest.raw",
        "action": "monitor",
    }


def run(path: Path, follow: bool, interval: float) -> None:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        if follow:
            handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                append_log(normalize(line, str(path)), kind="ingested")
                continue
            if not follow:
                break
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a real log into Wireshark AI JSONL")
    parser.add_argument("file", type=Path)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    run(args.file, args.follow, args.interval)


if __name__ == "__main__":
    main()
