# Decisions

Choices the PRD left open or implied, and the reasoning. Each is small enough to revisit.

## Lifecycle

**`approved` means "awaiting the click".** The PRD has an approval step and a send step but no name
for the time between them. In assisted fill that gap is the person reading the filled form before
clicking; in approved submission it's seconds. One state covers both: the approval is live, the
Guard is armed, nothing has been sent. Leaving it (by an edit, a revoke, or the 30-minute expiry)
returns to `in_review`.

**`drafted` can end as `draft_only`.** On draft-only destinations (and for anyone who prefers it)
the deliverable is the packet: every answer in form order with its sources, and the tailored résumé.
Closing the packet without sending is a terminal `draft_only`; sending it by hand is
`user_reported_submitted`. Both are honest about who did what.

**A late confirmation never rewrites history.** If an uncertain submission turns out to have gone
through, the person records it as a new outcome event. The lifecycle state stays
`submission_uncertain`, because that is what Lintel knew at the time. The weekly review counts it as
sent.

## Sending

**Only Lintel Lab allows agent-clicked submission at launch.** Real destinations start
`draft_only` with their terms review `pending` in the registry. An administrator moves a destination
to `assisted_fill` after reviewing its terms, and nothing becomes `approved_submission` without a
separate decision. The registry, not a model, decides.

**A bot challenge downgrades the destination for everyone.** Seeing a CAPTCHA on a destination is a
property of the destination, so it drops to assisted fill in the registry, not just for one person.
Lintel never solves, evades or clicks a challenge.

**Unexpected dialogs pause the run.** A cookie banner asks for a consent decision, so it belongs to
the person. The runner pauses with the dialog's text; the person closes it in the visible browser
and presses Resume.

**New questions on the live form are asked, not guessed.** Lever's public API doesn't list custom
questions, and any form can change. When the runner finds questions the payload doesn't cover, it
pauses as `missing_fact`; the questions appear in Lintel, the person answers, and the run resumes
on the same page.

**One running run per person.** A person has one visible browser and one attention. Runs queue
behind each other (a partial unique index enforces it), which also makes the runner simple to reason
about.

**Approvals last 30 minutes; fill grants 60.** Long enough to read and click, short enough that a
stale approval can't be used later. Both are signed with Ed25519 and verified by the runner before
it acts.

## Data

**Step logs keep a 16-hex-character SHA-256 prefix and a length, never the value.** Enough to show
that what was filled matches what was approved, without the cloud holding what the person typed.

**Evidence is text, not pictures.** The matched confirmation text, the reference number and a hash
of the page text. Screenshots would carry personal data the cloud doesn't need.

**Contacts are entered by the person, never scraped.** Referral asks and follow-ups are drafted for
the person to send. Lintel doesn't message anyone.

**The weekly budget follows the person's time zone.** Weeks start on Monday in the time zone they
set. When the budget is used, a "go" can be queued for next week instead.

## Models

**Offline by default.** Lintel runs with no model key: heuristic extraction and plain, literal
drafts, checked by the same claim check. With a key it drafts with Claude. Both paths fail closed.

**The claim check has a held-out set.** The checker was tuned on a development set of 84 sentences;
a second set of 40 was written afterwards and never used for tuning. The Trust Report's headline
numbers come from the held-out set, and its false blocks are shown, not hidden.

## Operations

**The queue lives in Postgres.** `FOR UPDATE SKIP LOCKED` on a jobs table is enough at this scale
and keeps every write in one database with one backup. In development the worker runs inside the
API process; in production run `lintel-api worker` separately.
