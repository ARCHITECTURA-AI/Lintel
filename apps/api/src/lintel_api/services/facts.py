"""The fact ledger.

Facts are append-only and immutable. Editing a fact creates a new one that supersedes the old.
A profile version is a set of fact ids, so every application names exactly what it was built from.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from lintel_schemas import AnswerCategory, ClaimScope, Fact, FactAttributes, FactHandle, FactKind, SourceType
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from ..db.models import ProfileFact, ProfileVersion
from ..errors import bad_request, conflict, not_found
from ..llm.base import FactSummary
from .core import audit

MODEL_VISIBLE_KINDS = {"role", "achievement", "skill", "education", "certification"}


def _current_clause(application_id: uuid.UUID | None):
    successor = aliased(ProfileFact)
    clause = and_(
        ProfileFact.retracted.is_(False),
        ~exists(select(successor.id).where(successor.supersedes_fact_id == ProfileFact.id)),
    )
    if application_id is None:
        return and_(clause, ProfileFact.application_scope_id.is_(None))
    return and_(clause, or_(ProfileFact.application_scope_id.is_(None), ProfileFact.application_scope_id == application_id))


def current_facts(db: Session, application_id: uuid.UUID | None = None) -> list[ProfileFact]:
    return list(db.scalars(select(ProfileFact).where(_current_clause(application_id)).order_by(ProfileFact.created_at)))


def to_schema(f: ProfileFact) -> Fact:
    return Fact(
        id=str(f.id),
        kind=FactKind(f.kind),
        claim_scope=ClaimScope(f.claim_scope),
        statement=f.statement,
        attributes=FactAttributes(**(f.attributes or {})),
        source_type=SourceType(f.source_type),
        source_ref=f.source_ref,
        supersedes_fact_id=str(f.supersedes_fact_id) if f.supersedes_fact_id else None,
        retracted=f.retracted,
        application_scope_id=str(f.application_scope_id) if f.application_scope_id else None,
        created_at=f.created_at,
    )


def summary(f: ProfileFact | Fact) -> FactSummary:
    attrs = f.attributes if isinstance(f.attributes, dict) else f.attributes.model_dump(exclude_none=True)
    return FactSummary(
        id=str(f.id),
        kind=str(f.kind.value if hasattr(f.kind, "value") else f.kind),
        claim_scope=str(f.claim_scope.value if hasattr(f.claim_scope, "value") else f.claim_scope),
        statement=f.statement,
        skills=list(attrs.get("skills") or []),
        employer=attrs.get("employer"),
        proficiency=attrs.get("proficiency"),
        start=attrs.get("start"),
        end=attrs.get("end"),
    )


def model_summaries(facts: list[ProfileFact]) -> list[FactSummary]:
    """Fact summaries a model may see: never contact, link, eligibility or demographic facts."""

    return [summary(f) for f in facts if f.kind in MODEL_VISIBLE_KINDS]


_VALID_SCOPES = {
    "contact": {"personal"},
    "link": {"personal"},
    "eligibility": {"personal"},
    "preference": {"personal"},
    "demographic": {"personal"},
    "role": {"employment", "project", "coursework"},
    "achievement": {"employment", "project", "coursework", "education", "personal"},
    "skill": {"employment", "project", "coursework", "personal"},
    "education": {"education"},
    "certification": {"certification"},
}


def add_fact(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    claim_scope: str,
    statement: str,
    attributes: dict[str, Any] | None = None,
    source_type: str,
    source_ref: str = "",
    supersedes: uuid.UUID | None = None,
    application_scope_id: uuid.UUID | None = None,
    actor: str = "user",
) -> ProfileFact:
    statement = re.sub(r"\s+", " ", statement or "").strip()
    if not statement:
        raise bad_request("empty_fact", "A fact needs a statement.")
    if kind not in _VALID_SCOPES:
        raise bad_request("bad_kind", f"Unknown fact kind {kind}.")
    if claim_scope not in _VALID_SCOPES[kind]:
        raise bad_request("bad_scope", f"A {kind} fact can't have scope {claim_scope}.")
    attrs = FactAttributes(**(attributes or {})).model_dump(exclude_none=True)
    attrs = {k: v for k, v in attrs.items() if v not in ([], "", None)}
    fact = ProfileFact(
        user_id=user_id,
        kind=kind,
        claim_scope=claim_scope,
        statement=statement,
        attributes=attrs,
        source_type=source_type,
        source_ref=source_ref,
        supersedes_fact_id=supersedes,
        application_scope_id=application_scope_id,
    )
    db.add(fact)
    db.flush()
    audit(db, user_id, actor, "fact.added" if not supersedes else "fact.superseded", "profile_fact", fact.id,
          kind=kind, scope=claim_scope, supersedes=str(supersedes) if supersedes else None)
    return fact


def _require_current(db: Session, fact_id: uuid.UUID) -> ProfileFact:
    fact = db.get(ProfileFact, fact_id)
    if fact is None:
        raise not_found("Fact not found.")
    succ = db.scalar(select(ProfileFact.id).where(ProfileFact.supersedes_fact_id == fact_id))
    if succ is not None:
        raise conflict("fact_superseded", "That fact was already replaced. Edit the newest version.",
                       {"current_fact_id": str(succ)})
    if fact.retracted:
        raise conflict("fact_retracted", "That fact was removed.")
    return fact


def supersede(db: Session, user_id: uuid.UUID, fact_id: uuid.UUID, *, statement: str | None = None,
              claim_scope: str | None = None, kind: str | None = None, attributes: dict[str, Any] | None = None,
              source_ref: str | None = None) -> ProfileFact:
    old = _require_current(db, fact_id)
    return add_fact(
        db,
        user_id,
        kind=kind or old.kind,
        claim_scope=claim_scope or old.claim_scope,
        statement=statement if statement is not None else old.statement,
        attributes=attributes if attributes is not None else old.attributes,
        source_type="user_entry" if old.source_type == "resume" else old.source_type,
        source_ref=source_ref or f"edited from {old.source_ref or 'earlier version'}",
        supersedes=old.id,
        application_scope_id=old.application_scope_id,
    )


def retract(db: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> ProfileFact:
    old = _require_current(db, fact_id)
    tomb = ProfileFact(
        user_id=user_id,
        kind=old.kind,
        claim_scope=old.claim_scope,
        statement=old.statement,
        attributes=old.attributes,
        source_type=old.source_type,
        source_ref="removed by you",
        supersedes_fact_id=old.id,
        retracted=True,
        application_scope_id=old.application_scope_id,
    )
    db.add(tomb)
    db.flush()
    audit(db, user_id, "user", "fact.retracted", "profile_fact", old.id)
    return tomb


def history(db: Session, fact_id: uuid.UUID) -> list[ProfileFact]:
    fact = db.get(ProfileFact, fact_id)
    if fact is None:
        raise not_found("Fact not found.")
    chain = [fact]
    cur = fact
    while cur.supersedes_fact_id:
        cur = db.get(ProfileFact, cur.supersedes_fact_id)
        if cur is None:
            break
        chain.insert(0, cur)
    cur = fact
    while True:
        nxt = db.scalar(select(ProfileFact).where(ProfileFact.supersedes_fact_id == cur.id))
        if nxt is None:
            break
        chain.append(nxt)
        cur = nxt
    return chain


def ensure_profile_version(db: Session, user_id: uuid.UUID, application_id: uuid.UUID | None) -> ProfileVersion:
    ids = sorted(str(f.id) for f in current_facts(db, application_id))
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    existing = db.scalar(select(ProfileVersion).where(ProfileVersion.fact_set_hash == digest))
    if existing:
        return existing
    pv = ProfileVersion(user_id=user_id, fact_ids=[uuid.UUID(i) for i in ids], fact_set_hash=digest)
    db.add(pv)
    db.flush()
    return pv


# ---------------------------------------------------------------------------
# Handles: names the field mapper may use. Values are resolved locally from facts.
# ---------------------------------------------------------------------------


def _role_sort_key(f: ProfileFact) -> tuple[int, str]:
    end = (f.attributes or {}).get("end") or ""
    start = (f.attributes or {}).get("start") or ""
    return (1 if end == "present" else 0, end if end != "present" else "9999", start)


def handle_values(facts: list[ProfileFact]) -> dict[str, tuple[str, str, AnswerCategory, str]]:
    """handle -> (value, fact_id, category, description)."""

    out: dict[str, tuple[str, str, AnswerCategory, str]] = {}

    def put(handle: str, value: Any, fact: ProfileFact, category: AnswerCategory, desc: str) -> None:
        if value in (None, "") or handle in out:
            return
        out[handle] = (str(value), str(fact.id), category, desc)

    for f in facts:
        a = f.attributes or {}
        field = a.get("field")
        if f.kind == "contact" and field:
            put(f"contact.{field}", a.get("value"), f, AnswerCategory.contact, f"Your {field.replace('_', ' ')}")
            if field == "full_name" and a.get("value"):
                parts = str(a["value"]).split()
                put("contact.first_name", parts[0], f, AnswerCategory.contact, "Your first name")
                if len(parts) > 1:
                    put("contact.last_name", " ".join(parts[1:]), f, AnswerCategory.contact, "Your last name")
        elif f.kind == "link" and field:
            put(f"links.{field}", a.get("value"), f, AnswerCategory.contact, f"Your {field} URL")
        elif f.kind == "eligibility" and field:
            country = (a.get("country") or "US").upper()
            put(f"eligibility.{field}.{country}", a.get("value"), f, AnswerCategory.eligibility,
                f"{'Authorized to work' if field == 'work_auth' else 'Needs visa sponsorship'} in {country}")
        elif f.kind == "preference" and field:
            put(f"prefs.{field}", a.get("value"), f, AnswerCategory.preference, f"Your {field.replace('_', ' ')}")
        elif f.kind == "demographic" and field:
            put(f"demographic.{field}", a.get("value"), f, AnswerCategory.demographic, f"Self-identification: {field}")

    roles = sorted([f for f in facts if f.kind == "role" and f.claim_scope == "employment"], key=_role_sort_key, reverse=True)
    for i, f in enumerate(roles[:5]):
        a = f.attributes or {}
        put(f"work[{i}].employer", a.get("employer"), f, AnswerCategory.contact, f"Employer of role {i + 1} (most recent first)")
        put(f"work[{i}].title", a.get("title"), f, AnswerCategory.contact, f"Title of role {i + 1}")
    edus = sorted([f for f in facts if f.kind == "education"], key=_role_sort_key, reverse=True)
    for i, f in enumerate(edus[:3]):
        a = f.attributes or {}
        put(f"education[{i}].school", a.get("school"), f, AnswerCategory.contact, f"School {i + 1}")
        put(f"education[{i}].degree", a.get("degree"), f, AnswerCategory.contact, f"Degree {i + 1}")
    return out


def handle_catalog(facts: list[ProfileFact]) -> list[FactHandle]:
    return [
        FactHandle(handle=h, description=desc, category=cat, fact_id=fid)
        for h, (_v, fid, cat, desc) in handle_values(facts).items()
    ]


_YES = {"yes", "y", "true", "authorized", "i am", "i do"}
_NO = {"no", "n", "false", "not authorized", "i am not", "i do not", "i don't"}


def match_option(value: str, options: list[dict[str, str]] | list[str]) -> str | None:
    """Pick the option a confirmed value means, or None. Never stretches a 'no' into a 'yes'."""

    opts = [o if isinstance(o, str) else (o.get("value") or o.get("label") or "") for o in options]
    labels = [o if isinstance(o, str) else (o.get("label") or o.get("value") or "") for o in options]
    v = (value or "").strip().lower()
    if not v:
        return None
    for o, lab in zip(opts, labels, strict=True):
        if v in (o.lower(), lab.lower()):
            return o
    yes = v in _YES or v.startswith("yes")
    no = v in _NO or v.startswith("no")
    for o, lab in zip(opts, labels, strict=True):
        ll = lab.lower()
        if yes and (ll.startswith("yes") or ll in _YES):
            return o
        if no and (ll.startswith("no") or ll in _NO):
            return o
    for o, lab in zip(opts, labels, strict=True):
        if lab.lower().startswith(v) or v.startswith(lab.lower()):
            return o
    return None
