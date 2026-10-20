from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db.models import Application, Job, UserTask
from ..deps import UserCtx
from ..errors import not_found
from ..serialize import row
from ..services import drafting, grounding
from ..services.core import close_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(ctx: UserCtx, status: str = "open") -> list[dict]:
    pairs = ctx.db.execute(
        select(UserTask, Application, Job)
        .outerjoin(Application, Application.id == UserTask.application_id)
        .outerjoin(Job, Job.id == Application.job_id)
        .where(UserTask.status == status)
        .order_by(UserTask.created_at.desc())
        .limit(200)
    ).all()
    return [
        row(t, application_state=a.state if a else None,
            job={"title": j.title, "company_name": j.company_name} if j else None)
        for t, a, j in pairs
    ]


def _task(ctx: UserCtx, task_id: uuid.UUID) -> UserTask:
    t = ctx.db.get(UserTask, task_id)
    if t is None:
        raise not_found("Task not found.")
    return t


class InterviewIn(BaseModel):
    answer: str = Field(default="", max_length=2000)
    claim_scope: str = "project"
    employer: str | None = Field(default=None, max_length=120)
    none: bool = False
    reusable: bool = True


@router.post("/{task_id}/interview")
def answer_interview(task_id: uuid.UUID, body: InterviewIn, ctx: UserCtx) -> dict:
    t = _task(ctx, task_id)
    fact = grounding.answer_interview(ctx.db, ctx.user, t, answer=body.answer, claim_scope=body.claim_scope,
                                      employer=body.employer, none=body.none, reusable=body.reusable)
    redrafted = None
    field_key = (t.data or {}).get("field_key")
    if t.type == "claim_review" and field_key and t.application_id and fact is not None:
        app = ctx.db.get(Application, t.application_id)
        redrafted = row(drafting.redraft(ctx.db, ctx.user, app, field_key))
    return {"fact": row(fact), "redrafted": redrafted}


@router.post("/{task_id}/dismiss")
def dismiss(task_id: uuid.UUID, ctx: UserCtx) -> dict:
    t = _task(ctx, task_id)
    if t.status == "open":
        close_task(t, "dismissed", {"by": "user"})
    return row(t)
