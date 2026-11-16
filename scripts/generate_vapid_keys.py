"""Generate a VAPID key pair for StudSovet Web Push notifications.

Run: python scripts/generate_vapid_keys.py
The private key is saved into ./data/vapid-private.pem; keep it secret and back it up.
"""
from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path = data_dir / "vapid-private.pem"
    if private_path.exists():
        raise SystemExit(f"Refusing to overwrite existing key: {private_path}")
    private_path.write_bytes(pem)
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")
    print("VAPID key pair created.")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    print("VAPID_PRIVATE_KEY=./data/vapid-private.pem")
    print("VAPID_CLAIMS_EMAIL=mailto:admin@example.org")
    print("Add these values to .env. Do not publish the private PEM file.")


if __name__ == "__main__":
    main()
