"""Run dependency and Python security scanners when installed.

Usage: python scripts/security_audit.py
Install optional scanners with: pip install -r requirements-security.txt
"""
from __future__ import annotations
import shutil
import subprocess
import sys

ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
checks = [
    ("pip-audit", ["pip-audit", "-r", str(ROOT / "requirements.txt")]),
    ("bandit", ["bandit", "-q", "-r", str(ROOT), "-x", "tests,static,templates,data,.git,.venv,venv,__pycache__"]),
]
missing = []
failed = False
for name, command in checks:
    if not shutil.which(command[0]):
        missing.append(name)
        continue
    print(f"\n== {name} ==", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    failed = failed or result.returncode != 0
if missing:
    print("\nНе установлены сканеры: " + ", ".join(missing))
    print("Установите их командой: pip install -r requirements-security.txt")
if failed:
    sys.exit(1)
if missing:
    sys.exit(2)
print("\nSecurity audit completed without scanner findings.")
