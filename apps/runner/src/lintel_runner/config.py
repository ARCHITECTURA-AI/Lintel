"""Local Runner configuration. Login state and cookies never leave this machine."""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("lintel.runner")

HOME = Path(os.environ.get("LINTEL_RUNNER_HOME", Path.home() / ".lintel"))
KEYRING_SERVICE = "lintel-runner"


@dataclass
class RunnerConfig:
    api_url: str = os.environ.get("LINTEL_API_URL", "http://localhost:8000")
    device_id: str | None = None
    device_name: str | None = None
    public_key_pem: str | None = None
    headless: bool = os.environ.get("LINTEL_HEADLESS", "0") == "1"
    extra: dict = field(default_factory=dict)

    @property
    def profile_dir(self) -> Path:
        # A dedicated browser profile, never the person's everyday one.
        return HOME / "browser-profile"

    @property
    def docs_dir(self) -> Path:
        return HOME / "documents"

    @property
    def journal_path(self) -> Path:
        return HOME / "journal.jsonl"


def _config_path() -> Path:
    return HOME / "config.json"


def load() -> RunnerConfig:
    cfg = RunnerConfig()
    p = _config_path()
    if p.exists():
        data = json.loads(p.read_text())
        for k, v in data.items():
            if hasattr(cfg, k) and k != "headless":
                setattr(cfg, k, v)
    if os.environ.get("LINTEL_API_URL"):
        cfg.api_url = os.environ["LINTEL_API_URL"]
    return cfg


def save(cfg: RunnerConfig) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    data.pop("headless", None)
    _config_path().write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# The per-device token lives in the operating system keychain.
# ---------------------------------------------------------------------------


def _fallback_token_path() -> Path:
    return HOME / ".device-token"


def store_token(device_id: str, token: str) -> str:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, device_id, token)
        if keyring.get_password(KEYRING_SERVICE, device_id) == token:
            _fallback_token_path().unlink(missing_ok=True)
            return "keychain"
    except Exception as exc:  # noqa: BLE001 - no keychain backend (headless Linux, CI)
        log.warning("OS keychain unavailable (%s); storing the device token in a 0600 file instead", type(exc).__name__)
    HOME.mkdir(parents=True, exist_ok=True)
    path = _fallback_token_path()
    path.write_text(token)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return str(path)


def load_token(device_id: str | None) -> str | None:
    if os.environ.get("LINTEL_DEVICE_TOKEN"):
        return os.environ["LINTEL_DEVICE_TOKEN"]
    if not device_id:
        return None
    try:
        import keyring

        tok = keyring.get_password(KEYRING_SERVICE, device_id)
        if tok:
            return tok
    except Exception:  # noqa: BLE001
        pass
    path = _fallback_token_path()
    return path.read_text().strip() if path.exists() else None


def forget(device_id: str | None) -> None:
    if device_id:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, device_id)
        except Exception:  # noqa: BLE001
            pass
    _fallback_token_path().unlink(missing_ok=True)
    _config_path().unlink(missing_ok=True)
