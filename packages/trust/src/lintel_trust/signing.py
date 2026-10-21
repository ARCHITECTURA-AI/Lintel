"""Signed approvals and fill grants.

The server signs the payload hash, the device id and the expiry with Ed25519. The Local Runner
holds only the public key, so it can verify a grant but can never mint one. A stale or tampered
payload cannot pass the Guard.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from lintel_schemas import SignedApproval, SignedFillGrant


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _claims_bytes(kind: str, claims: dict[str, Any]) -> bytes:
    body = {"kind": kind, **claims}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def generate_private_key_pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def load_private_key(pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("approval signing key must be Ed25519")
    return key


def public_key_pem(private: Ed25519PrivateKey) -> str:
    return (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def load_public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("approval verification key must be Ed25519")
    return key


def _approval_claims(a: SignedApproval | dict[str, Any]) -> dict[str, Any]:
    d = a.model_dump() if isinstance(a, SignedApproval) else a
    return {
        "approval_id": d["approval_id"],
        "application_id": d["application_id"],
        "payload_hash": d["payload_hash"],
        "runner_device_id": d["runner_device_id"],
        "expires_at": _iso(d["expires_at"]),
        "key_id": d.get("key_id", "lintel-1"),
    }


def _grant_claims(g: SignedFillGrant | dict[str, Any]) -> dict[str, Any]:
    d = g.model_dump() if isinstance(g, SignedFillGrant) else g
    return {
        "run_id": d["run_id"],
        "application_id": d["application_id"],
        "payload_hash": d["payload_hash"],
        "runner_device_id": d["runner_device_id"],
        "expires_at": _iso(d["expires_at"]),
        "key_id": d.get("key_id", "lintel-1"),
    }


def sign_approval(
    key: Ed25519PrivateKey,
    *,
    approval_id: str,
    application_id: str,
    payload_hash: str,
    runner_device_id: str,
    expires_at: datetime,
    key_id: str = "lintel-1",
) -> SignedApproval:
    claims = {
        "approval_id": approval_id,
        "application_id": application_id,
        "payload_hash": payload_hash,
        "runner_device_id": runner_device_id,
        "expires_at": expires_at,
        "key_id": key_id,
    }
    sig = key.sign(_claims_bytes("approval", _approval_claims(claims)))
    return SignedApproval(**claims, signature=_b64(sig))


def sign_fill_grant(
    key: Ed25519PrivateKey,
    *,
    run_id: str,
    application_id: str,
    payload_hash: str,
    runner_device_id: str,
    expires_at: datetime,
    key_id: str = "lintel-1",
) -> SignedFillGrant:
    claims = {
        "run_id": run_id,
        "application_id": application_id,
        "payload_hash": payload_hash,
        "runner_device_id": runner_device_id,
        "expires_at": expires_at,
        "key_id": key_id,
    }
    sig = key.sign(_claims_bytes("fill_grant", _grant_claims(claims)))
    return SignedFillGrant(**claims, signature=_b64(sig))


class SignatureError(Exception):
    pass


def verify_approval(
    public: Ed25519PublicKey,
    approval: SignedApproval,
    *,
    payload_hash: str,
    runner_device_id: str,
    now: datetime | None = None,
) -> None:
    """Raise SignatureError unless the approval is authentic, unexpired and for this payload and device."""

    try:
        public.verify(_unb64(approval.signature), _claims_bytes("approval", _approval_claims(approval)))
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("approval signature is invalid") from exc
    if approval.payload_hash != payload_hash:
        raise SignatureError("approval was signed for a different payload")
    if approval.runner_device_id != runner_device_id:
        raise SignatureError("approval was signed for a different device")
    now = now or datetime.now(UTC)
    exp = approval.expires_at if approval.expires_at.tzinfo else approval.expires_at.replace(tzinfo=UTC)
    if exp <= now:
        raise SignatureError("approval has expired")


def verify_fill_grant(
    public: Ed25519PublicKey,
    grant: SignedFillGrant,
    *,
    payload_hash: str,
    runner_device_id: str,
    now: datetime | None = None,
) -> None:
    try:
        public.verify(_unb64(grant.signature), _claims_bytes("fill_grant", _grant_claims(grant)))
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("fill grant signature is invalid") from exc
    if grant.payload_hash != payload_hash:
        raise SignatureError("fill grant was signed for a different payload")
    if grant.runner_device_id != runner_device_id:
        raise SignatureError("fill grant was signed for a different device")
    now = now or datetime.now(UTC)
    exp = grant.expires_at if grant.expires_at.tzinfo else grant.expires_at.replace(tzinfo=UTC)
    if exp <= now:
        raise SignatureError("fill grant has expired")
