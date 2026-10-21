"""Private encrypted object storage. Approvals bind to hashes, not filenames.

Files are encrypted with AES-256-GCM before they touch disk. The SHA-256 recorded for each
document is of the plaintext, so the runner can verify an upload byte for byte.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


def _root() -> Path:
    root = get_settings().storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _aead() -> AESGCM:
    return AESGCM(get_settings().resolved_storage_key())


def put(user_id: uuid.UUID, data: bytes) -> tuple[str, str]:
    """Store bytes for a user. Returns (storage_key, sha256 of the plaintext)."""

    digest = hashlib.sha256(data).hexdigest()
    key = f"{user_id}/{uuid.uuid4()}.bin"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(12)
    path.write_bytes(nonce + _aead().encrypt(nonce, data, str(user_id).encode()))
    return key, digest


def get(user_id: uuid.UUID, storage_key: str) -> bytes:
    if not storage_key.startswith(f"{user_id}/"):
        raise PermissionError("document belongs to another user")
    blob = (_root() / storage_key).read_bytes()
    return _aead().decrypt(blob[:12], blob[12:], str(user_id).encode())


def delete(user_id: uuid.UUID, storage_key: str) -> None:
    if storage_key.startswith(f"{user_id}/"):
        (_root() / storage_key).unlink(missing_ok=True)


def delete_user(user_id: uuid.UUID) -> None:
    shutil.rmtree(_root() / str(user_id), ignore_errors=True)
