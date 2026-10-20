"""Application lifecycle and run state machines.

The lifecycle is what the user sees: nine states to confirmation and the exits around them.
Execution attempts live in runs. Both tables are mirrored by database triggers so the rules
hold even if application code is wrong.
"""

from .enums import ApplicationState as S
from .enums import RunState as R

TERMINAL_STATES: frozenset[S] = frozenset(
    {
        S.confirmed,
        S.draft_only,
        S.skipped,
        S.submission_uncertain,
        S.user_reported_submitted,
        S.cancelled,
        S.expired,
    }
)

# The three human gates.
GATE_STATES: frozenset[S] = frozenset({S.fit_review, S.grounding, S.in_review})

HAPPY_PATH: tuple[S, ...] = (
    S.imported,
    S.fit_review,
    S.grounding,
    S.drafted,
    S.filling,
    S.in_review,
    S.approved,
    S.submitting,
    S.confirmed,
)

_ANY_LIVE_EXIT = {S.cancelled, S.expired}

TRANSITIONS: dict[S, frozenset[S]] = {
    # imported -> draft_only when the destination is prohibited and Lintel won't prepare for it
    S.imported: frozenset({S.fit_review, S.draft_only} | _ANY_LIVE_EXIT),
    S.fit_review: frozenset({S.grounding, S.skipped} | _ANY_LIVE_EXIT),
    # grounding can loop back to fit review if the user changes their mind about the role
    S.grounding: frozenset({S.drafted, S.fit_review, S.skipped} | _ANY_LIVE_EXIT),
    # drafted -> grounding when a draft surfaces a new fact question.
    # On a draft-only destination the drafted packet is the product: the user sends it by hand
    # (user_reported_submitted) or closes it (draft_only).
    S.drafted: frozenset({S.filling, S.grounding, S.draft_only, S.user_reported_submitted} | _ANY_LIVE_EXIT),
    S.filling: frozenset({S.in_review, S.drafted, S.user_reported_submitted} | _ANY_LIVE_EXIT),
    # in_review -> filling to re-fill after an edit; in_review -> drafted after a payload change
    S.in_review: frozenset({S.approved, S.filling, S.drafted, S.user_reported_submitted} | _ANY_LIVE_EXIT),
    # approved -> in_review when the approval is revoked, expires or the Guard reports a mismatch
    S.approved: frozenset({S.submitting, S.in_review, S.user_reported_submitted} | _ANY_LIVE_EXIT),
    # submitting never goes back: the outcome is confirmed or uncertain
    S.submitting: frozenset({S.confirmed, S.submission_uncertain}),
}
for _t in TERMINAL_STATES:
    TRANSITIONS[_t] = frozenset()


def can_transition(src: S | str, dst: S | str) -> bool:
    return S(dst) in TRANSITIONS.get(S(src), frozenset())


STATE_LABELS: dict[S, str] = {
    S.imported: "Imported",
    S.fit_review: "Fit review",
    S.grounding: "Grounding",
    S.drafted: "Drafted",
    S.filling: "Filling",
    S.in_review: "In review",
    S.approved: "Approved",
    S.submitting: "Submitting",
    S.confirmed: "Confirmed",
    S.draft_only: "Draft-only",
    S.skipped: "Skipped",
    S.submission_uncertain: "Submission uncertain",
    S.user_reported_submitted: "User reported sent",
    S.cancelled: "Cancelled",
    S.expired: "Expired",
}

ACTIVE_RUN_STATES: frozenset[R] = frozenset({R.queued, R.running, R.waiting_user})
TERMINAL_RUN_STATES: frozenset[R] = frozenset({R.completed, R.failed, R.cancelled})

RUN_TRANSITIONS: dict[R, frozenset[R]] = {
    R.queued: frozenset({R.running, R.cancelled}),
    R.running: frozenset({R.waiting_user, R.completed, R.failed, R.cancelled}),
    # resuming creates a new run; the waiting run is closed as cancelled with reason "resumed"
    R.waiting_user: frozenset({R.completed, R.failed, R.cancelled}),
    R.completed: frozenset(),
    R.failed: frozenset(),
    R.cancelled: frozenset(),
}
