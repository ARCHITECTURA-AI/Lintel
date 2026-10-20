"""Passwords, opaque tokens and the approval signing key."""

from __future__ import annotations

import functools
import hashlib
import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lintel_trust import load_private_key, public_key_pem

from .config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# A real hash to compare against when the email is unknown, so timing does not reveal accounts.
DUMMY_HASH = _hasher.hash("lintel-dummy-password")


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_user_code() -> str:
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


@functools.lru_cache
def signing_key() -> Ed25519PrivateKey:
    return load_private_key(get_settings().resolved_signing_key_pem())


@functools.lru_cache
def signing_public_pem() -> str:
    return public_key_pem(signing_key())
