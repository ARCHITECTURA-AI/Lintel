from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..db import set_user
from ..db.models import User
from ..deps import SESSION_COOKIE, AnonDb, UserCtx
from ..errors import ApiError
from ..security import DUMMY_HASH, hash_password, new_token, token_hash, verify_password
from ..serialize import row
from ..services.core import audit, now

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _start_session(db, response: Response, request: Request, user_id) -> None:
    s = get_settings()
    token = new_token("ls")
    db.execute(
        text("SELECT auth_create_session(:u, :h, :e, :a)"),
        {"u": user_id, "h": token_hash(token), "e": now() + timedelta(days=s.session_days),
         "a": request.headers.get("user-agent", "")[:300]},
    )
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_days * 86400, path="/")


def me_payload(user: User) -> dict:
    return row(user, exclude={"model_daily_cap_usd"}) | {"onboarded": bool((user.onboarding or {}).get("done"))}


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: AnonDb) -> dict:
    try:
        with db.begin_nested():
            uid = db.scalar(text("SELECT auth_register(:e, :h, :n)"),
                            {"e": body.email.lower(), "h": hash_password(body.password), "n": body.full_name.strip()})
    except IntegrityError as exc:
        raise ApiError(409, "email_taken", "An account with that email already exists. Sign in instead.") from exc
    set_user(db, uid)
    user = db.get(User, uid)
    audit(db, uid, "user", "account.created", "user", uid)
    _start_session(db, response, request, uid)
    return me_payload(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: AnonDb) -> dict:
    found = db.execute(text("SELECT id, password_hash FROM auth_lookup(:e)"), {"e": body.email.lower()}).first()
    if not verify_password(found.password_hash if found else DUMMY_HASH, body.password) or not found:
        raise ApiError(401, "bad_credentials", "That email and password don't match.")
    set_user(db, found.id)
    _start_session(db, response, request, found.id)
    return me_payload(db.get(User, found.id))


@router.post("/logout")
def logout(ctx: UserCtx, request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        ctx.db.execute(text("UPDATE sessions SET revoked_at = now() WHERE token_hash = :h"), {"h": token_hash(token)})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: UserCtx) -> dict:
    return me_payload(ctx.user)
