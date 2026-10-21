"""`lintel-evals`: run the evaluations and write the Trust Report.

    uv run lintel-evals              # claim check + properties + the end-to-end suite (needs Postgres)
    uv run lintel-evals --quick      # claim check only, no database
    uv run lintel-evals --publish    # also copy the report to docs/trust-report.json

The report lands in evals/out/report.json; the API serves it at /public/trust-report and the web
app renders it at /trust. Failures are published next to successes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lintel_schemas import CheckOutcome
from lintel_trust.claimcheck import check_sentence
from lintel_trust.claimcheck.verifier import HeuristicVerifier

from .claims import CASES, CONTEXT, FACTS, HELD_OUT, Case, facts_for

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evals" / "out" / "report.json"
PUBLISHED = ROOT / "docs" / "trust-report.json"

WILL_NOT_DO = [
    "Click submit on a site whose terms haven't been reviewed and approved, or on any site but Lintel Lab at launch.",
    "Solve, evade or route around a CAPTCHA or any other bot challenge.",
    "Guess eligibility, sponsorship, salary or demographic answers.",
    "Send anything you haven't approved, byte for byte, on the device you approved it for.",
    "Retry a submission it can't confirm. It marks it uncertain and asks you.",
    "Message recruiters or referrers for you. It drafts; you send.",
    "Keep your site logins or cookies in the cloud.",
]

LIMITS = [
    "The claim check is strongest on specifics (numbers, tools, employers, titles, degrees). Vague praise that is "
    "technically true can pass, and some true sentences are blocked until you rephrase or confirm a fact.",
    "Exactly once is “as far as known”: when the runner dies between the click and the confirmation, Lintel can't "
    "know whether the site received it, so it says “submission uncertain” and never retries.",
    "Lab results are from Lintel Lab skins that copy public patterns. Real employer forms vary; adapters are "
    "versioned per destination in the registry.",
    "The offline drafter is plain and literal. Drafts read better with a model key, and are checked the same way.",
    "No feature here promises interviews. Interviews per sent application is reported with its interval.",
]


def score(cases: list[Case]) -> dict[str, Any]:
    all_facts = list(FACTS.values())
    rows = []
    for c in cases:
        r = check_sentence(c.sentence, facts_for(c), all_facts=all_facts, context_terms=CONTEXT,
                           verifier=HeuristicVerifier(context_terms=CONTEXT))
        failed = [x for x in r.checks if x.outcome == CheckOutcome.failed]
        rows.append((c, r.passed, failed))
    unsupported = [x for x in rows if not x[0].supported]
    supported = [x for x in rows if x[0].supported]
    leaked = [x for x in unsupported if x[1]]
    blocked = [x for x in supported if not x[1]]
    verifier_caught = sum(1 for c, _, failed in unsupported if any(f.name == "verifier" for f in failed))
    cats: dict[str, Counter] = defaultdict(Counter)
    for c, passed, _ in unsupported:
        cats[c.category]["cases"] += 1
        cats[c.category]["leaked" if passed else "caught"] += 1
    return {
        "cases": len(rows),
        "supported": len(supported),
        "unsupported": len(unsupported),
        "unsupported_leaked": len(leaked),
        "leakage_rate": round(len(leaked) / max(1, len(unsupported)), 4),
        "verifier_recall": round(verifier_caught / max(1, len(unsupported)), 4),
        "false_blocks": len(blocked),
        "by_category": [{"category": k, "cases": v["cases"], "caught": v["caught"], "leaked": v["leaked"]}
                        for k, v in sorted(cats.items())],
        "_rows": rows,
    }


def claim_check() -> dict[str, Any]:
    dev = score(CASES)
    held = score(HELD_OUT)
    examples = []
    for c, _passed, failed in held["_rows"]:
        if not c.supported and failed and len(examples) < 6 and c.category not in {e["category"] for e in examples}:
            examples.append({"sentence": c.sentence, "verdict": "blocked", "reason": failed[0].detail,
                             "category": c.category})
    for c, passed, failed in held["_rows"]:
        if c.supported and not passed:
            examples.append({"sentence": c.sentence, "verdict": "false block", "reason": failed[0].detail,
                             "category": c.category})
        if not c.supported and passed:
            examples.append({"sentence": c.sentence, "verdict": "leaked", "reason": "passed every check",
                             "category": c.category})
    out = {k: v for k, v in held.items() if k != "_rows"}
    out["examples"] = examples
    out["development"] = {k: v for k, v in dev.items() if k not in ("_rows", "examples", "by_category")}
    out["note"] = ("Headline numbers are from a held-out set written after the checker was tuned and never used to "
                   "tune it. The development set the checker was tuned on is reported separately.")
    return out


def beta_exit(r: dict[str, Any]) -> list[dict[str, Any]]:
    """The PRD's proposed beta exit criteria, measured on Lintel Lab."""

    b = r.get("beta")
    if not b:
        return []
    prep = b["prepared"] / max(1, b["attempted"])
    acc = b["fields_ok"] / max(1, b["fields_checked"])
    rls = next((p for p in r.get("property_tests", []) if p["name"].startswith("No cross-user")), None)
    resent = sum(1 for c in r.get("crash_tests", []) if c.get("resent"))
    return [
        {"criterion": "Preparation completion on Lintel Lab flows", "target": "at least 90%",
         "value": f"{prep:.0%} ({b['prepared']} of {b['attempted']})", "passed": prep >= 0.9},
        {"criterion": "Field accuracy on Lintel Lab flows", "target": "at least 95%",
         "value": f"{acc:.1%} ({b['fields_ok']} of {b['fields_checked']} read back)", "passed": acc >= 0.95},
        {"criterion": "Unapproved sends", "target": "0", "value": str(b["unapproved_intents"]),
         "passed": b["unapproved_intents"] == 0},
        {"criterion": "Cross-user exposure", "target": "0",
         "value": "0" if rls and rls["passed"] else "see property tests", "passed": bool(rls and rls["passed"])},
        {"criterion": "Automatic retries of uncertain sends", "target": "0", "value": str(resent), "passed": resent == 0},
    ]


def headline(r: dict[str, Any]) -> list[dict[str, Any]]:
    h: list[dict[str, Any]] = []
    cc = r["claim_check"]
    h.append({"label": "Unsupported claims leaked", "value": f"{cc['unsupported_leaked']} of {cc['unsupported']}",
              "target": "0", "ok": cc["unsupported_leaked"] == 0})
    if r.get("crash_tests"):
        sends = sum(1 for c in r["crash_tests"] if c.get("resent"))
        h.append({"label": "Duplicate sends under crashes", "value": str(sends), "target": "0",
                  "ok": sends == 0 and all(c.get("passed") for c in r["crash_tests"])})
    if r.get("guard"):
        g = r["guard"]
        h.append({"label": "Guard blocks on changed fields", "value": f"{g['blocked']} of {g['injected_mismatches']}",
                  "target": "all", "ok": g["blocked"] == g["injected_mismatches"]})
    if r.get("lab"):
        ok = sum(1 for x in r["lab"] if x.get("passed"))
        h.append({"label": "Lintel Lab flows passing", "value": f"{ok} of {len(r['lab'])}", "target": "all",
                  "ok": ok == len(r["lab"])})
    if r.get("property_tests") and len(h) < 4:
        ok = sum(1 for x in r["property_tests"] if x["passed"])
        h.append({"label": "Property tests", "value": f"{ok} of {len(r['property_tests'])}", "ok": ok == len(r["property_tests"])})
    return h


def main() -> None:
    ap = argparse.ArgumentParser(prog="lintel-evals")
    ap.add_argument("--quick", action="store_true", help="claim check only; no database or browser")
    ap.add_argument("--no-e2e", action="store_true", help="skip the end-to-end suite")
    ap.add_argument("--publish", action="store_true", help="copy the report to docs/trust-report.json")
    args = ap.parse_args()

    report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "version": "0.1.0"}
    print("claim check…", flush=True)
    report["claim_check"] = claim_check()
    if not args.quick:
        from .properties import run_properties

        print("property tests…", flush=True)
        report["property_tests"] = run_properties()
        if not args.no_e2e:
            from .harness import running_stack
            from .scenarios import run_all

            print("end-to-end suite (Postgres, API, Lab, headless runner)…", flush=True)
            with running_stack() as stack:
                e2e = run_all(stack, log=lambda m: print(f"  {m}", flush=True))
            guard = e2e.pop("guard")
            report.update({k: v for k, v in e2e.items() if k != "seconds"})
            report["guard"] = {"injected_mismatches": guard.get("injected_mismatches", 1),
                               "blocked": guard.get("blocked", 0), "detail": guard.get("detail", "")}
            report["e2e_seconds"] = e2e["seconds"]
            report["beta"] = e2e["beta"]
            report["beta_exit"] = beta_exit(report)
    report["headline"] = headline(report)
    report["will_not_do"] = WILL_NOT_DO
    report["limits"] = LIMITS
    report["note"] = ("Generated by `uv run lintel-evals` against a fresh database, the Lintel Lab and the shipped "
                      "runner in a headless browser. Nothing is mocked; failing rows stay in the report.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print(f"wrote {OUT}")
    if args.publish:
        PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(OUT, PUBLISHED)
        print(f"published {PUBLISHED}")
    failed = [h["label"] for h in report["headline"] if h.get("ok") is False]
    failed += [b["criterion"] for b in report.get("beta_exit", []) if not b["passed"]]
    if failed:
        print("failing: " + "; ".join(failed), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
