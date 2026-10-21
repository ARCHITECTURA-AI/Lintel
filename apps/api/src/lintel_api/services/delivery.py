"""Notification delivery: in-app first, then email, then web push.

One daily digest by default, and an immediate message only when a run is blocked. Emails carry
links only, never résumé content or answers, and every link needs a signed-in session.
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import EmailOutbox, Notification, PushSubscription, User
from .core import now

log = logging.getLogger("lintel.delivery")


def _send_email(row: EmailOutbox) -> None:
    s = get_settings()
    if not s.smtp_host:
        row.status = "logged"
        row.sent_at = now()
        log.info("email (no SMTP configured) to=%s subject=%s\n%s", row.to_address, row.subject, row.body_text)
        return
    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = row.to_address
    msg["Subject"] = row.subject
    msg.set_content(row.body_text)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        row.status = "sent"
        row.sent_at = now()
    except Exception as exc:  # noqa: BLE001
        row.status = "failed"
        row.error = str(exc)[:300]


def _push(db: Session, user: User, n: Notification) -> bool:
    s = get_settings()
    if not (s.vapid_private_key and s.vapid_public_key):
        return False
    subs = list(db.scalars(select(PushSubscription)))
    if not subs:
        return False
    from pywebpush import WebPushException, webpush

    ok = False
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": n.title, "body": n.body, "url": n.link}),
                vapid_private_key=s.vapid_private_key,
                vapid_claims={"sub": s.vapid_subject},
                timeout=10,
            )
            ok = True
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                db.delete(sub)
    return ok


def deliver(db: Session, user: User) -> dict[str, int]:
    s = get_settings()
    prefs = user.notification_prefs or {}
    out = {"emailed": 0, "pushed": 0}
    pending = list(db.scalars(select(Notification).where(Notification.read_at.is_(None), Notification.emailed_at.is_(None))
                              .order_by(Notification.created_at)))
    urgent = [n for n in pending if n.urgent]
    for n in urgent:
        if prefs.get("email", True):
            row = EmailOutbox(user_id=user.id, to_address=user.email, subject=f"Lintel: {n.title}",
                              body_text=f"{n.body}\n\nOpen Lintel: {s.web_origin}{n.link}\n\n(You'll be asked to sign in.)")
            db.add(row)
            _send_email(row)
            out["emailed"] += 1
        n.emailed_at = now()
        if prefs.get("push") and n.pushed_at is None and _push(db, user, n):
            n.pushed_at = now()
            out["pushed"] += 1
    return out


def daily_digest(db: Session, user: User) -> bool:
    s = get_settings()
    prefs = user.notification_prefs or {}
    if not prefs.get("email", True) or prefs.get("digest", "daily") == "off":
        return False
    last = db.scalar(select(EmailOutbox.created_at).where(EmailOutbox.subject.like("Lintel daily%")).order_by(EmailOutbox.created_at.desc()))
    if last and now() - last < timedelta(hours=23):
        return False
    items = list(db.scalars(select(Notification).where(Notification.read_at.is_(None), Notification.emailed_at.is_(None))
                            .order_by(Notification.created_at)))
    if not items:
        return False
    lines = [f"- {n.title}: {n.body}" for n in items[:12]]
    row = EmailOutbox(user_id=user.id, to_address=user.email, subject=f"Lintel daily: {len(items)} update(s)",
                      body_text="Here's what changed in Lintel.\n\n" + "\n".join(lines)
                      + f"\n\nOpen your dashboard: {s.web_origin}/\n(You'll be asked to sign in.)")
    db.add(row)
    _send_email(row)
    for n in items:
        n.emailed_at = now()
    return True
