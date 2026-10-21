"""Request context: one transaction per request, under row-level security for the caller."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import set_user, user_session
from .db.models import RunnerDevice, User
from .errors import ApiError
from .security import token_hash

SESSION_COOKIE = "lintel_session"


@dataclass
class Ctx:
    db: Session
    user: User

    @property
    def uid(self) -> uuid.UUID:
        return self.user.id


@dataclass
class RunnerCtx:
    db: Session
    user: User
    device: RunnerDevice

    @property
    def uid(self) -> uuid.UUID:
        return self.user.id


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _user_ctx(request: Request) -> Iterator[Ctx]:
    token = request.cookies.get(SESSION_COOKIE) or _bearer(request)
    with user_session(None) as db:
        uid = None
        if token and token.startswith("ls_"):
            uid = db.scalar(text("SELECT auth_session_user(:h)"), {"h": token_hash(token)})
        if not uid:
            raise ApiError(401, "unauthenticated", "Sign in to continue.")
        set_user(db, uid)
        user = db.get(User, uid)
        if user is None:
            raise ApiError(401, "unauthenticated", "Sign in to continue.")
        yield Ctx(db=db, user=user)


def _runner_ctx(request: Request) -> Iterator[RunnerCtx]:
    token = _bearer(request)
    with user_session(None) as db:
        row = None
        if token and token.startswith("lr_"):
            row = db.execute(text("SELECT device_id, user_id FROM auth_device(:h)"), {"h": token_hash(token)}).first()
        if not row:
            raise ApiError(401, "runner_unpaired", "This runner is not paired, or it was revoked.")
        set_user(db, row.user_id)
        user = db.get(User, row.user_id)
        device = db.get(RunnerDevice, row.device_id)
        if user is None or device is None:
            raise ApiError(401, "runner_unpaired", "This runner is not paired, or it was revoked.")
        yield RunnerCtx(db=db, user=user, device=device)


def _anon_db() -> Iterator[Session]:
    with user_session(None) as db:
        yield db


UserCtx = Annotated[Ctx, Depends(_user_ctx, scope="function")]
DeviceCtx = Annotated[RunnerCtx, Depends(_runner_ctx, scope="function")]
AnonDb = Annotated[Session, Depends(_anon_db, scope="function")]
