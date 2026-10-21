"""Provider selection with per-user spend caps.

Every model call is metered into model_usage under the user's row-level security. When a
user's daily cap is spent, Lintel falls back to the offline heuristics instead of failing.
"""

from __future__ import annotations

import functools
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import ModelUsage, User
from .base import Provider
from .offline import OfflineProvider

ROLE_OF = {
    "extract_requirements": "extractor",
    "map_fields": "extractor",
    "extract_resume_facts": "extractor",
    "assess_requirements": "drafter",
    "draft_answer": "drafter",
    "propose_variant": "drafter",
    "interview_question": "drafter",
    "verify": "verifier",
}


def _base_provider() -> Provider:
    s = get_settings()
    choice = s.llm_provider
    key = s.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if choice == "offline" or (choice == "auto" and not key):
        return OfflineProvider()
    from .anthropic_provider import AnthropicProvider

    return AnthropicProvider(
        key,
        extractor_model=s.extractor_model,
        drafter_model=s.drafter_model,
        verifier_model=s.verifier_model,
        fallbacks=s.llm_fallbacks,
    )


@functools.lru_cache
def shared_provider() -> Provider:
    return _base_provider()


class MeteredProvider:
    def __init__(self, inner: Provider, session: Session, user_id: uuid.UUID):
        self.inner = inner
        self.offline = OfflineProvider()
        self.session = session
        self.user_id = user_id
        self.capped = False

    @property
    def name(self) -> str:
        return "offline" if self.capped else self.inner.name

    def _spent_today(self) -> Decimal:
        since = datetime.now(UTC) - timedelta(days=1)
        return self.session.scalar(
            select(func.coalesce(func.sum(ModelUsage.cost_usd), 0)).where(
                ModelUsage.user_id == self.user_id, ModelUsage.created_at >= since
            )
        ) or Decimal(0)

    def __getattr__(self, item: str) -> Any:
        target = getattr(self.inner, item)
        if item not in ROLE_OF or isinstance(self.inner, OfflineProvider):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            cap = self.session.scalar(select(User.model_daily_cap_usd).where(User.id == self.user_id)) or Decimal("2")
            if self._spent_today() >= cap:
                self.capped = True
                return getattr(self.offline, item)(*args, **kwargs)
            try:
                return target(*args, **kwargs)
            finally:
                for u in self.inner.last_usage():
                    self.session.add(
                        ModelUsage(
                            user_id=self.user_id,
                            role=ROLE_OF[item],
                            provider=self.inner.name,
                            model=u.model,
                            input_tokens=u.input_tokens,
                            output_tokens=u.output_tokens,
                            cost_usd=Decimal(str(round(u.cost_usd, 6))),
                        )
                    )

        return call


def provider_for(session: Session, user_id: uuid.UUID) -> MeteredProvider:
    return MeteredProvider(shared_provider(), session, user_id)
