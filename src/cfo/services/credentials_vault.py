"""
Symmetric encryption for integration credentials stored in the database.

The Fernet key is derived from CREDENTIALS_ENCRYPTION_KEY (or, as a fallback,
JWT_SECRET_KEY) so deployments work without an extra mandatory variable.
Legacy rows that were stored as plain JSON are still readable.
"""
import base64
import hashlib
import json
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


def _fernet() -> Fernet:
    key_material = settings.credentials_encryption_key or settings.jwt_secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())
    return Fernet(key)


def encrypt_credentials(credentials: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(blob: Optional[str]) -> dict[str, Any]:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        # Row predates encryption — stored as plain JSON.
        try:
            return json.loads(blob)
        except ValueError:
            return {}
