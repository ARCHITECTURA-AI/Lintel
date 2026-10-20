"""Enumerations shared by every Lintel component.

String enums keep the wire format, the database and the TypeScript types in step.
"""

from enum import StrEnum


class Platform(StrEnum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    unknown = "unknown"


class SupportMode(StrEnum):
    """Who performs the final click. The registry decides, never a model."""

    draft_only = "draft_only"  # Nobody. Lintel produces a copyable packet.
    assisted_fill = "assisted_fill"  # The user, after the Submit Guard checks the form.
    approved_submission = "approved_submission"  # Lintel, once, after exact approval.


class PolicyReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ClaimScope(StrEnum):
    """What kind of claim a fact can support. A project can never be written up as a job."""

    employment = "employment"
    project = "project"
    coursework = "coursework"
    education = "education"
    certification = "certification"
    personal = "personal"  # contact details, eligibility and preferences about the person


class FactKind(StrEnum):
    contact = "contact"
    link = "link"
    role = "role"  # a position held: employer, title, dates
    achievement = "achievement"  # something done, with evidence
    skill = "skill"
    education = "education"
    certification = "certification"
    eligibility = "eligibility"  # work authorization, sponsorship
    preference = "preference"  # relocation, notice period, salary, start date
    demographic = "demographic"  # voluntary self-identification answers


class SourceType(StrEnum):
    resume = "resume"
    user_entry = "user_entry"
    user_interview = "user_interview"


class ApplicationState(StrEnum):
    """What the user sees. Execution lives in runs."""

    imported = "imported"
    fit_review = "fit_review"  # gate 1
    grounding = "grounding"  # gate 2
    drafted = "drafted"
    filling = "filling"
    in_review = "in_review"  # gate 3
    approved = "approved"  # approval active, awaiting the click
    submitting = "submitting"
    confirmed = "confirmed"
    # exits
    draft_only = "draft_only"
    skipped = "skipped"
    submission_uncertain = "submission_uncertain"
    user_reported_submitted = "user_reported_submitted"
    cancelled = "cancelled"
    expired = "expired"


class RunState(StrEnum):
    queued = "queued"
    running = "running"
    waiting_user = "waiting_user"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunKind(StrEnum):
    read_form = "read_form"  # open the page and build a FormModel, no writes
    fill = "fill"  # fill fields from the pinned payload, never submit
    submit = "submit"  # arm the Submit Guard (or click once in approved_submission)


class Actor(StrEnum):
    user = "user"
    system = "system"
    worker = "worker"
    runner = "runner"


class FitLabel(StrEnum):
    strong = "strong"
    possible = "possible"
    stretch = "stretch"
    conflict = "conflict"


class Recommendation(StrEnum):
    apply = "apply"
    skip = "skip"
    ask = "ask"


class RequirementStatus(StrEnum):
    met = "met"
    gap = "gap"
    uncertain = "uncertain"


class MappingDecisionKind(StrEnum):
    handle = "handle"
    draft_needed = "draft_needed"
    ask_user = "ask_user"
    skip = "skip"


class AnswerCategory(StrEnum):
    """Answer categories and the unknown-answer policy (carried from v1, section 13)."""

    contact = "contact"  # resolved from facts by handle, never sent to a model
    eligibility = "eligibility"  # never guessed: the user answers, Lintel reuses only if told to
    preference = "preference"  # never guessed
    demographic = "demographic"  # defaults to "decline to self-identify" unless the user set one
    free_text = "free_text"  # drafted from cited facts, then claim checked
    consent = "consent"  # the user ticks it themselves at review
    document = "document"  # résumé or attachment, matched by hash
    unknown = "unknown"  # ask the user


class OutcomeStage(StrEnum):
    prepared = "prepared"
    submitted = "submitted"
    user_reported_submitted = "user_reported_submitted"
    submission_uncertain = "submission_uncertain"
    acknowledged = "acknowledged"
    no_reply = "no_reply"
    rejected = "rejected"
    recruiter_screen = "recruiter_screen"
    interview = "interview"
    final_round = "final_round"
    offer = "offer"
    accepted = "accepted"
    declined = "declined"
    withdrawn = "withdrawn"


class OutcomeSource(StrEnum):
    adapter = "adapter"
    user = "user"
    email = "email"
    system = "system"


class TaskType(StrEnum):
    fact_interview = "fact_interview"
    unknown_answer = "unknown_answer"
    claim_review = "claim_review"
    waiting_user = "waiting_user"
    guard_mismatch = "guard_mismatch"
    confirm_submission = "confirm_submission"
    follow_up = "follow_up"
    referral = "referral"


class CheckOutcome(StrEnum):
    passed = "pass"
    failed = "fail"
    skipped = "skipped"


class VerifierVerdict(StrEnum):
    supported = "supported"
    overreach = "overreach"
    unsupported = "unsupported"


class FieldType(StrEnum):
    text = "text"
    textarea = "textarea"
    email = "email"
    tel = "tel"
    url = "url"
    number = "number"
    date = "date"
    select = "select"
    radio = "radio"
    checkbox = "checkbox"
    multiselect = "multiselect"
    file = "file"


POSITIVE_OUTCOME_STAGES = {
    OutcomeStage.recruiter_screen,
    OutcomeStage.interview,
    OutcomeStage.final_round,
    OutcomeStage.offer,
    OutcomeStage.accepted,
}
REPLY_OUTCOME_STAGES = POSITIVE_OUTCOME_STAGES | {OutcomeStage.rejected, OutcomeStage.declined}
# A recruiter screen counts as an interview: it is the first conversation the paperwork earned.
INTERVIEW_OUTCOME_STAGES = set(POSITIVE_OUTCOME_STAGES)
