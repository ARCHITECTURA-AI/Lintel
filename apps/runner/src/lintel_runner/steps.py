"""Step log without secrets. Each step records the field key, a hash and length of the value, and the
verification result. Values never leave the machine in a step record."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from lintel_schemas import RunStepRecord
from lintel_trust import value_hash

from .client import Api, ApiError

log = logging.getLogger("lintel.runner")


class StepLog:
    def __init__(self, api: Api, run_id: str):
        self.api = api
        self.run_id = run_id
        self.seq = 0
        self.pending: list[RunStepRecord] = []
        self.actions = 0

    def add(self, action: str, *, field_key: str | None = None, value: Any = None, verification: str = "ok",
            detail: str = "") -> None:
        self.seq += 1
        vh, vl = value_hash(value) if value not in (None, "") else (None, None)
        self.pending.append(RunStepRecord(seq=self.seq, action=action, field_key=field_key, value_hash=vh, value_len=vl,
                                          verification=verification, detail=detail[:400]))
        if action in ("fill", "select", "check", "upload", "click", "navigate"):
            self.actions += 1
        if len(self.pending) >= 8:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        batch = [s.model_dump(mode="json") for s in self.pending]
        try:
            self.api.post(f"/runner/runs/{self.run_id}/steps", json=batch)
            self.pending = []
        except ApiError as exc:
            if exc.code == "budget_exhausted":
                self.pending = []
                raise
            log.warning("step upload failed (%s); will retry", exc)

    def retarget(self, run_id: str) -> None:
        self.flush()
        self.run_id = run_id
        self.seq = 0


class Journal:
    """A local append-only journal of intents and outcomes, for the person's own records."""

    def __init__(self, path):
        self.path = path

    def write(self, **event: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **event}) + "\n")
