# Lintel

**The agent prepares, you sign off.** Lintel is a supervised job-application agent. It finds roles
on the boards you watch, writes a fit brief, asks you what only you can answer, drafts every answer
from facts you confirmed, fills the employer's form in a browser on your own machine, and stops at
the submit button until you approve the exact payload. Every claim traces to a fact; every send
happens once, as far as anyone can know; and when Lintel can't know, it says so.

```
Find → Fit brief* → Ground* → Draft → Fill → Review* → Send → Learn          * a human gate
```

## What's here

| Path | What it is |
| --- | --- |
| `apps/web` | Next.js 16 app: Today, the fit queue, the application workspace (gates, drafts, review, audit trail), the fact ledger, outcomes, the runner, settings and the public Trust Report |
| `apps/api` | FastAPI service on Postgres: ledger, discovery, fit briefs, grounding, drafting and the claim check, approvals, runs, outcomes, privacy. Row-level security on every user table |
| `apps/runner` | The Local Runner (`lintel`): a visible browser on your machine, the policy gate, the Submit Guard, and the write-ahead submit intent |
| `packages/schemas` | Shared Pydantic models, enums and the application lifecycle. Generates the web app's TypeScript types |
| `packages/trust` | Canonical payload hashing, Ed25519 approval signing, and the claim check (token, scope and verifier stages) |
| `lab` | Lintel Lab: a local test site with Greenhouse-, Lever- and Ashby-style boards and every awkward case (conditional fields, multi-step, modal, session expiry, CAPTCHA placeholder, timeout after submit, validation, prompt injection) |
| `evals` | The end-to-end harness, crash and Lab scenarios, the claim-check evaluation set, database property tests, and `lintel-evals`, which writes the Trust Report |
| `docs` | Architecture, decisions, and the published Trust Report |

## Run it

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22 with pnpm, and Postgres 16
(`scripts/dev-db.sh` starts a local cluster on port 5433, or use `docker compose up -d`).

```bash
uv sync                                  # Python workspace
pnpm install                             # web app
scripts/dev-db.sh                        # Postgres on 127.0.0.1:5433 (databases lintel and lintel_test)
uv run lintel-api migrate                # schema, row-level security, the destination registry
scripts/svc.sh start lab api webdev      # Lab :4100, API :8000, web :3000 (dev server)
uv run lintel-api demo                   # demo@lintel.dev / lintel-demo-2026, wired to the Lab
```

Open http://localhost:3000 and sign in with the demo account. To let Lintel fill forms, pair a
runner on the **Local Runner** page:

```bash
uv run lintel pair --api http://localhost:8000   # shows a code; enter it in the web app
uv run lintel start                              # opens a visible browser and waits for work
```

### Models

Lintel runs fully offline by default (`LINTEL_LLM_PROVIDER=offline`): plain heuristic extraction and
drafting, checked by the same claim check. Set `ANTHROPIC_API_KEY` and `LINTEL_LLM_PROVIDER=auto`
to draft with Claude; `LINTEL_EXTRACTOR_MODEL`, `LINTEL_DRAFTER_MODEL` and `LINTEL_VERIFIER_MODEL`
choose the models, and a per-user daily spend cap falls back to offline when reached. A model never
decides a support mode, never sees a field's value, and never clicks.

## Tests and the Trust Report

```bash
uv run pytest -m "not e2e"     # unit and integration tests (uses lintel_test; skipped if Postgres is down)
uv run pytest -m e2e           # the shipped runner, headless, against Lintel Lab
uv run lintel-evals            # claim-check eval, property tests and the full end-to-end suite
uv run lintel-evals --publish  # ...and copy the report to docs/trust-report.json
```

The integration and end-to-end tests run the real stack: a freshly migrated database, the API and
the Lab as subprocesses, and the `lintel` runner in a headless browser. Nothing is mocked. The crash
suite kills the runner at each step of the submit sequence and checks, from the database and from the
Lab's own record of what it received, that nothing is ever sent twice.

`lintel-evals` writes `evals/out/report.json`; the API serves it at `/public/trust-report` and the
web app renders it at `/trust`. Failing rows stay in the report. See [docs/trust-report.md](docs/trust-report.md).

## Read more

- [docs/architecture.md](docs/architecture.md): how the pieces fit, and where each promise is enforced
- [docs/decisions.md](docs/decisions.md): choices the PRD left open, and why
- [docs/trust-report.md](docs/trust-report.md): what the Trust Report measures and how
