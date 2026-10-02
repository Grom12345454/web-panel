#!/usr/bin/env bash
set -euo pipefail
MODEL="${QWEN_MODEL:-qwen2.5:7b}"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it from https://ollama.com/download, then rerun this script."
  exit 1
fi
systemctl enable --now ollama 2>/dev/null || true
ollama pull "$MODEL"
echo "Qwen model ready: $MODEL"
