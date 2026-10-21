# Architecture

Lintel is three programs and a database. The web app is where the person decides. The API keeps the
ledger, drafts and checks, and records every decision. The Local Runner, on the person's own
machine, is the only thing that touches an employer's site. Postgres enforces the rules that make
the product's promises true, so they hold even if application code is wrong.

```
 ┌──────────── web (Next.js) ────────────┐        ┌──────── Local Runner (lintel) ────────┐
 │ gates · drafts · review · audit trail │        │ visible browser · policy gate · Guard │
 └──────────────────┬────────────────────┘        └──────────────────┬────────────────────┘
          session cookie                                   device token (keychain)
                    │                                                │
              ┌─────▼────────────────────────────────────────────────▼─────┐
              │ API (FastAPI) · llm provider · claim check · signing key   │
              │ queue worker and scheduler (embedded in development)       │
              └─────────────────────────────┬──────────────────────────────┘
                                            │ SET ROLE lintel_app, app.user_id per transaction
                                    ┌───────▼────────┐
                                    │ Postgres 16    │  RLS · triggers · SECURITY DEFINER entry points
                                    └────────────────┘
```

## The loop and its records

| Step | What happens | Where it's recorded |
| --- | --- | --- |
| Find | Public board feeds (Greenhouse, Lever, Ashby) for watched companies; target matches become applications | `watched_companies`, `jobs`, `applications` (`imported`) |
| **Fit brief** | Requirements met with evidence, gaps, uncertain items, hard-filter conflicts; go or skip within a weekly budget | `applications.fit_brief`, `fit_review` → `grounding` or `skipped` |
| **Ground** | Each form field mapped to a fact handle, drafted, or asked of the person. Eligibility, sponsorship, salary and demographics are never inferred. Fact Interview questions surface real experience | `answer_drafts`, `user_tasks`, `profile_facts` (`user_interview`) |
| Draft | Free-text answers drafted from cited facts, sentence by sentence, each through the claim check; a tailored résumé variant whose changes are diffed and checked | `answer_drafts.sentences`, `resume_variants` |
| Fill | The runner fills the employer's form in a visible browser, reading every value back; new questions on the live form pause the run and are asked | `application_runs`, `run_steps` (value hash and length, never values) |
| **Review** | The exact canonical payload, its hash, and the mode (who clicks). Approval is signed with Ed25519 and bound to the payload hash and the runner device, for 30 minutes | `approval_records` |
| Send | The Submit Guard compares the live form with the approval; a write-ahead submit intent with a fencing token is recorded before the click is let through; the outcome is keyed by that fence | `submit_intents`, `outcome_events`, `evidence` |
| Learn | Stages from sent to offer, follow-ups after the no-reply window, referral asks, a weekly review with Wilson intervals | `outcome_events`, `follow_ups`, `contacts` |

## Lifecycle and runs

An application has one lifecycle state (`packages/schemas/src/lintel_schemas/lifecycle.py`); runs
are separate execution attempts (`queued → running → waiting_user → completed | failed | cancelled`).
The allowed transitions are generated into the database at migration time, and a trigger refuses
any other change, any change without a named actor and reason, and any change out of a terminal
state. Every transition is recorded. The property tests check that the database accepts exactly the
transitions the spec allows.

## Where each promise is enforced

**Only confirmed facts are claimed.** The claim check (`packages/trust/src/lintel_trust/claimcheck`)
runs on every drafted or edited sentence: a token check (numbers, tools, organizations, months,
names must appear in a cited fact), a scope check (employment needs an employment fact, at the
right employer; "familiar with" never becomes "expert"; leadership, degrees and certifications need
a fact that says so; projects aren't jobs), then a verifier (a model when configured, a
conservative heuristic otherwise). It fails closed: a failing sentence is redrafted once with the
failure as feedback, then becomes a question for the person.

**Nothing is sent without approval of the exact payload.** The canonical payload (sorted keys,
NFC-normalized UTF-8) is hashed with SHA-256. Any edit changes the hash and revokes a live
approval. The runner verifies the approval signature locally before acting. The Guard runs in the
page's capture phase on click, submit and Enter, after the browser's own validation, and compares
every field and every uploaded file hash with the approval.

**Never sent twice on Lintel's authority.** `begin_submit()` locks the application row, checks
state, payload hash, job still open and the approval (unconsumed, unrevoked, unexpired, this
device), consumes the approval, increments the fence and writes the intent, all in one
transaction. Only after it commits does the click go through. `record_submit_outcome()` accepts
only the current fence, once. An intent with no outcome becomes `submission_uncertain`, which is
never armed or retried; the person records what happened. The runner journals intent, click and
outcome locally too.

**The registry decides who clicks, never a model.** `destinations.support_mode` is
`draft_only`, `assisted_fill` (the person clicks; the Guard checks) or `approved_submission`
(Lintel clicks once; Lintel Lab only at launch). In assisted fill the runner's policy gate has no
submit tool at all. A bot challenge drops a destination to assisted fill automatically; Lintel never
touches a challenge.

**The runner can only do what the payload says.** The policy gate (`apps/runner/.../gate.py`)
checks every action: the tool exists in this mode and run kind, the field is in the current form
model and page version and visible, the value comes from the payload, uploads match an approved
document hash, navigation stays on registry hosts. Page text is data; the planner reads fields, not
prose.

**People's data stays theirs.** Every user table has row-level security keyed on `app.user_id`,
set per transaction; the API drops to `lintel_app` on connect. Work that happens before a user is
known (sign-in, pairing, the job queue) goes through narrow `SECURITY DEFINER` functions. Logins
and cookies live only in the runner's own browser profile. Export is a zip of everything; erasure
removes the account and its documents.

## Models

`apps/api/src/lintel_api/llm` defines one provider interface with two implementations: Claude
through the Anthropic API (structured outputs, separate extractor, drafter and verifier models) and
an offline provider that needs no key. A metered wrapper enforces a per-user daily spend cap and
falls back to offline. Models see fact statements and questions; they never see field values for
contact or eligibility handles, never choose a support mode, and never act on a page.
