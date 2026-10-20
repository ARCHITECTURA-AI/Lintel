from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LINTEL_", env_file=(ROOT / ".env"), extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://lintel@127.0.0.1:5433/lintel"
    # The API connects as the owner and drops to this role per connection, so row-level security
    # applies to every query. In production, connect directly as a login role and leave it empty.
    db_app_role: str = "lintel_app"

    data_dir: Path = ROOT / ".data"
    signing_key_pem: str | None = None
    storage_key_b64: str | None = None

    web_origin: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    session_days: int = 30

    llm_provider: str = "auto"  # auto | anthropic | offline
    anthropic_api_key: str | None = None
    # Two roles from the PRD (extractor and drafter) plus the verifier. Each can be set separately.
    extractor_model: str = "claude-opus-5-5"
    drafter_model: str = "claude-opus-5-5"
    verifier_model: str = "claude-opus-5-5"
    # Server-side refusal fallback (routes a policy decline to a fallback model in the same call).
    llm_fallbacks: bool = True

    approval_ttl_minutes: int = 30
    fill_grant_ttl_minutes: int = 60
    run_lease_seconds: int = 90
    submit_uncertain_after_seconds: int = 120
    feed_poll_hours: int = 6
    feed_min_manual_interval_minutes: int = 5
    step_log_retention_days: int = 90

    run_max_actions: int = 50
    run_max_recoveries_per_step: int = 2
    run_max_active_minutes: int = 15

    lab_base_url: str = "http://localhost:4100"
    admin_emails: str = ""

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "Lintel <noreply@lintel.local>"

    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:admin@lintel.local"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def resolved_signing_key_pem(self) -> str:
        if self.signing_key_pem:
            return self.signing_key_pem
        path = self.keys_dir / "approval_ed25519.pem"
        if not path.exists():
            if self.env == "production":
                raise RuntimeError("LINTEL_SIGNING_KEY_PEM must be set in production")
            from lintel_trust import generate_private_key_pem

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generate_private_key_pem())
            os.chmod(path, 0o600)
        return path.read_text()

    def resolved_storage_key(self) -> bytes:
        if self.storage_key_b64:
            return base64.b64decode(self.storage_key_b64)
        path = self.keys_dir / "storage.key"
        if not path.exists():
            if self.env == "production":
                raise RuntimeError("LINTEL_STORAGE_KEY_B64 must be set in production")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64encode(os.urandom(32)))
            os.chmod(path, 0o600)
        return base64.b64decode(path.read_bytes())


@lru_cache
def get_settings() -> Settings:
    return Settings()
