"""Lintel trust engine.

Five pieces make Lintel different from an autofill tool. This package holds the parts that are
pure logic: the canonical payload and its hash, signed approvals, value normalization for the
Submit Guard, and the claim check. The fact ledger, write-ahead intents and fencing live in
Postgres, enforced by the database.
"""

from .canonical import canonical_form, canonical_json, payload_hash, sha256_bytes, value_hash
from .normalize import normalize_value, values_equal
from .signing import (
    SignatureError,
    generate_private_key_pem,
    load_private_key,
    load_public_key,
    public_key_pem,
    sign_approval,
    sign_fill_grant,
    verify_approval,
    verify_fill_grant,
)

__all__ = [
    "SignatureError",
    "canonical_form",
    "canonical_json",
    "generate_private_key_pem",
    "load_private_key",
    "load_public_key",
    "normalize_value",
    "payload_hash",
    "public_key_pem",
    "sha256_bytes",
    "sign_approval",
    "sign_fill_grant",
    "value_hash",
    "values_equal",
    "verify_approval",
    "verify_fill_grant",
]
