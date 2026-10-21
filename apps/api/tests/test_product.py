"""The API through the same HTTP surface the web app uses, against a real database and Lintel Lab."""

from __future__ import annotations

import io
import subprocess
import sys
import zipfile

import httpx
import psycopg
import pytest
from lintel_evals.harness import ROOT, owner_conn, wait_until

BACKEND = "Backend Engineer, Platform"
CONFLICT = "AI Engineer, Applied LLMs"


def _plain(stack, email: str) -> httpx.Client:
    c = httpx.Client(base_url=stack.api_url, timeout=30)
    r = c.post("/auth/register", json={"email": email, "password": "a-long-password-1", "full_name": "Test Person"})
    assert r.status_code == 200, r.text
    return c


# -- accounts and isolation ------------------------------------------------------------------------


def test_requests_without_a_session_are_refused(stack):
    assert httpx.get(f"{stack.api_url}/facts").status_code == 401
    assert httpx.get(f"{stack.api_url}/applications").status_code == 401


def test_one_person_never_sees_another_persons_data(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    fact_id = a.get("/facts")[0]["id"]
    b = _plain(stack, "isolated@lintel.dev")
    assert b.get("/facts").json() == []
    assert b.get("/applications").json() == []
    assert b.get(f"/applications/{aid}").status_code == 404
    assert b.post(f"/facts/{fact_id}/retract").status_code in (403, 404)
    # And underneath the API: row-level security as the application role, with B's id set.
    with owner_conn() as c:
        b_id = c.execute("SELECT id FROM users WHERE email = 'isolated@lintel.dev'").fetchone()[0]
        with c.transaction():
            c.execute("SET LOCAL ROLE lintel_app")
            c.execute("SELECT set_config('app.user_id', %s, true)", (str(b_id),))
            assert c.execute("SELECT count(*) FROM profile_facts").fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM applications").fetchone()[0] == 0
        with c.transaction():
            c.execute("SET LOCAL ROLE lintel_app")
            assert c.execute("SELECT count(*) FROM profile_facts").fetchone()[0] == 0  # no user set: no rows


# -- the ledger --------------------------------------------------------------------------------


def test_the_fact_ledger_is_append_only(stack, account):
    a = account("acme")
    fact = next(f for f in a.get("/facts") if f["kind"] == "achievement")
    new = a.post(f"/facts/{fact['id']}/supersede", {"statement": fact["statement"] + " Reviewed by two engineers."}).json()
    assert new["supersedes_fact_id"] == fact["id"]
    ids = {f["id"] for f in a.get("/facts")}
    assert new["id"] in ids and fact["id"] not in ids
    assert [h["id"] for h in a.get(f"/facts/{new['id']}/history")][-2:] in ([fact["id"], new["id"]], [new["id"], fact["id"]])
    with owner_conn() as c, pytest.raises(psycopg.Error):
        c.execute("UPDATE profile_facts SET statement = 'rewritten' WHERE id = %s", (fact["id"],))


# -- gate 1 -----------------------------------------------------------------------------------


def test_fit_brief_flags_hard_filter_conflicts_and_keeps_policy_lines_out(stack, account):
    a = account("acme")
    aid = a.app_id(CONFLICT)
    a.wait_state(aid, "fit_review")
    brief = a.detail(aid)["application"]["fit_brief"]
    assert brief["label"] == "conflict" and brief["recommendation"] == "skip"
    assert any(c["filter"] == "Sponsorship" for c in brief["conflicts"])
    assert not any("sponsor" in r["text"].lower() for r in brief["requirements"])
    assert all(r["status"] != "met" or r["evidence_fact_ids"] for r in brief["requirements"])


def test_the_weekly_budget_holds(stack, account):
    a = account("initech")
    a.c.patch("/me", json={"weekly_budget": 1}).raise_for_status()
    first = a.app_id("Platform Engineer (unexpected modal)")
    second = a.app_id("Platform Engineer (session expiry)")
    for aid in (first, second):
        a.wait_state(aid, "fit_review")
    a.post(f"/applications/{first}/decide", {"go": True})
    r = a.post(f"/applications/{second}/decide", {"go": True}, ok=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "budget_full"
    a.post(f"/applications/{second}/decide", {"go": True, "next_week": True})
    assert a.detail(second)["application"]["week_budget_slot"]


# -- gate 2 and drafting ----------------------------------------------------------------------


def test_eligibility_is_asked_never_guessed(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    a.wait_state(aid, "fit_review")
    a.post(f"/applications/{aid}/decide", {"go": True})
    a.wait_state(aid, "grounding")
    d = a.detail(aid)
    eligibility = [x for x in d["drafts"] if x["category"] == "eligibility"]
    assert eligibility and all(x["decision"] == "ask_user" for x in eligibility)
    r = a.post(f"/applications/{aid}/grounding/confirm", ok=False)
    assert r.status_code == 409 and r.json()["error"]["code"] == "questions_open"


def test_the_claim_check_blocks_an_unsupported_edit(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    d = a.to_drafted(aid)
    dr = next(x for x in d["drafts"] if x["decision"] == "draft_needed")
    r = a.c.put(f"/applications/{aid}/drafts/{dr['field_key']}",
                json={"text": dr["value"] + " I led a team of 5 engineers to scale it to 10,000 users."})
    edited = r.json()
    assert edited["status"] == "blocked", edited
    assert not a.detail(aid)["readiness"]["ready"]
    checks = a.post(f"/applications/{aid}/check", {"text": "I am an expert in Kubernetes. I worked at Google."}).json()
    assert all(not s["check"]["passed"] for s in checks)


def test_a_changed_payload_needs_a_new_approval(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    a.to_drafted(aid)
    a.fill(aid)
    old_hash = a.detail(aid)["application"]["payload_hash"]
    a.approve(aid, "assisted_fill")
    assert a.state(aid) == "approved"
    a.post(f"/applications/{aid}/revoke")
    assert a.state(aid) == "in_review"
    d = a.detail(aid)
    dr = next(x for x in d["drafts"] if x["decision"] == "draft_needed")
    a.c.put(f"/applications/{aid}/drafts/{dr['field_key']}", json={"text": dr["sentences"][0]["text"]}).raise_for_status()
    new_hash = a.detail(aid)["application"]["payload_hash"]
    assert new_hash != old_hash
    r = a.post(f"/applications/{aid}/approve", {"payload_hash": old_hash}, ok=False)
    assert r.status_code == 409


# -- outcomes, follow-ups, export and erasure --------------------------------------------------


def test_outcome_loop_follow_up_export_and_erasure(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    a.to_drafted(aid)
    a.post(f"/applications/{aid}/report-sent", {"note": "sent from the packet"})
    assert a.state(aid) == "user_reported_submitted"
    fu = next(f for f in a.detail(aid)["follow_ups"] if f["kind"] == "follow_up")
    assert fu["status"] == "scheduled"
    drafted = a.post(f"/follow-ups/{fu['id']}/draft").json()
    assert drafted["draft"] and all(s["check"]["passed"] for s in drafted["draft_sentences"]), drafted["draft_sentences"]
    a.post(f"/applications/{aid}/outcomes", {"stage": "interview", "note": "first round"})
    # A reply makes the follow-up moot.
    assert all(f["status"] == "dismissed" for f in a.detail(aid)["follow_ups"] if f["kind"] == "follow_up")
    review = a.get("/outcomes/review", params={"weeks": 4})
    assert review["sent"] == 1 and review["interviews"] == 1
    lo, hi = review["ci"]
    assert 0 <= lo < hi <= 1 and hi - lo > 0.5  # one application: the interval is honest, and wide

    z = zipfile.ZipFile(io.BytesIO(a.c.get("/me/export").content))
    names = set(z.namelist())
    assert {"account.json", "profile_facts.json", "applications.json", "README.txt"} <= names
    assert any(n.startswith("documents/") for n in names)

    assert a.post("/me/delete", {"confirm": "wrong@example.com"}, ok=False).status_code == 400
    a.post("/me/delete", {"confirm": a.email})
    assert a.c.post("/auth/login", json={"email": a.email, "password": "lintel-test-2026"}).status_code == 401
    with owner_conn() as c:
        assert c.execute("SELECT count(*) FROM users WHERE email = %s", (a.email,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM applications WHERE id = %s", (aid,)).fetchone()[0] == 0


def test_draft_only_packet_can_be_closed(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    a.to_drafted(aid)
    packet = a.get(f"/applications/{aid}/packet")
    assert packet["items"] and packet["payload_hash"]
    a.post(f"/applications/{aid}/close-packet")
    assert a.state(aid) == "draft_only"


# -- the runner over HTTP ------------------------------------------------------------------------


def test_one_fill_then_one_send(stack, account):
    a = account("acme")
    aid = a.app_id(BACKEND)
    a.to_drafted(aid)
    a.fill(aid)
    d = a.detail(aid)
    assert d["application"]["state"] == "in_review"
    assert d["fill"]["current"] and all(s["value_hash"] is None or len(s["value_hash"]) == 16 for s in d["steps"])
    a.approve(aid, "approved_submission")
    a.run_runner()
    assert wait_until(lambda: a.state(aid) == "confirmed", 20)
    got = [r for r in stack.lab_submissions() if r["posting_id"] == "4412" and r["email"]]
    assert len([r for r in got if r["reference"] in str(a.detail(aid)["evidence"])]) == 1
    events = [j["event"] for j in a.journal()]
    assert events[:3] == ["intent", "clicked", "outcome"]


def test_generated_types_match_the_models():
    r = subprocess.run([sys.executable, "-m", "lintel_schemas.gen_ts", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
