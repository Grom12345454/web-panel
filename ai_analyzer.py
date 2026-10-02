#!/usr/bin/env python3
"""Qwen2.5 log analysis through a local Ollama endpoint, with safe fallback rules."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from typing import Any

DEFAULT_URL = os.environ.get("QWEN_URL", "http://127.0.0.1:11434/api/generate")
DEFAULT_MODEL = os.environ.get("QWEN_MODEL", "qwen2.5:7b")


def _rule_analysis(logs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(x.get("type", "safe")) for x in logs)
    protocols = Counter(str(x.get("protocol", "unknown")) for x in logs)
    rules = Counter(str(x.get("rule", "unknown")) for x in logs if x.get("type") != "safe")
    top_rules = [{"rule": k, "count": v} for k, v in rules.most_common(8)]
    findings = []
    for rule, count in rules.most_common(5):
        findings.append({"severity": "high" if rule.startswith("threat.") else "medium", "title": rule, "count": count})
    return {
        "provider": "rule-engine",
        "model": "fallback",
        "summary": f"Проанализировано {len(logs)} событий: threat={counts['danger']}, suspicious={counts['warn']}, normal={counts['safe']}.",
        "findings": findings,
        "topProtocols": [{"protocol": k, "count": v} for k, v in protocols.most_common(8)],
        "topRules": top_rules,
        "recommendations": [
            "Проверить повторяющиеся threat.* правила и связанные source IP.",
            "Сопоставить DNS, SMB, RDP и SSH события с базовой линией сети.",
            "Для автоматической блокировки оставить включённым analyst review gate.",
        ],
    }


def analyze(logs: list[dict[str, Any]], *, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, timeout: int = 30) -> dict[str, Any]:
    if not logs:
        return _rule_analysis([])

    compact = []
    for item in logs[-40:]:
        compact.append({k: item.get(k) for k in ("time", "src", "dst", "domain", "port", "protocol", "type", "severity", "rule", "signature", "country", "packets", "bytes")})

    prompt = """Ты SOC-аналитик. Проанализируй JSONL сетевых событий. Не выдумывай факты. Отделяй наблюдение от гипотезы. Верни только JSON с полями summary, findings, topProtocols, topRules, recommendations. findings — массив объектов severity,title,evidence. recommendations — короткие защитные действия. Не предлагай вредоносные действия."""
    body = json.dumps({"model": model, "prompt": prompt + "\nEVENTS:\n" + json.dumps(compact, ensure_ascii=False), "stream": False, "format": "json", "options": {"temperature": 0.1}}, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("response", "{}")
        result = json.loads(raw) if isinstance(raw, str) else raw
        result["provider"] = "ollama"
        result["model"] = model
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        result = _rule_analysis(logs)
        result["aiError"] = str(exc)
        return result
