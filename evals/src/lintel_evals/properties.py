"""Property tests against the real database: the rules that make "exactly once, as far as known" true.

Each property runs many generated examples through Postgres itself (row locks, triggers,
constraints), with concurrent connections where the property is about races.
"""

from __future__ import annotations

import secrets
import threading
import unicodedata
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from lintel_schemas import ApplicationState, can_transition
from lintel_schemas.lifecycle import TRANSITIONS
from lintel_trust import payload_hash

from .harness import TEST_DSN

DSN = TEST_DSN.replace("+psycopg", "")
HASH = "a" * 64


def _conn() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True)


def _path_to(target: str) -> list[str]:
    """Shortest legal path from imported to target, from the shared lifecycle table."""

    start = ApplicationState.imported.value
    prev: dict[str, str | None] = {start: None}
    q = deque([start])
    while q:
        s = q.popleft()
        if s == target:
            break
        for t in TRANSITIONS.get(ApplicationState(s), ()):
            if t.value not in prev:
                prev[t.value] = s
                q.append(t.value)
    if target not in prev:
        raise ValueError(f"{target} is unreachable")
    path, cur = [], target
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def _move(c: psycopg.Connection, app_id: uuid.UUID, state: str) -> None:
    with c.transaction():
        c.execute("SELECT set_config('lintel.actor', 'system', true), set_config('lintel.reason', 'property test', true)")
        c.execute("UPDATE applications SET state = %s WHERE id = %s", (state, app_id))


def make_application(c: psycopg.Connection, state: str = "approved") -> dict[str, Any]:
    """A user, a device, a job and an application walked through legal transitions to `state`."""

    uid = c.execute("INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
                    (f"prop-{secrets.token_hex(6)}@lintel.test",)).fetchone()[0]
    dev = c.execute("INSERT INTO runner_devices (user_id, name, token_hash) VALUES (%s, 'prop', %s) RETURNING id",
                    (uid, secrets.token_hex(16))).fetchone()[0]
    job = c.execute(
        "INSERT INTO jobs (user_id, platform, board_name, posting_id, title, company_name, apply_url, host) "
        "VALUES (%s, 'lab', 'prop', %s, 'Engineer', 'Prop Co', 'http://lab/apply', 'lab') RETURNING id",
        (uid, secrets.token_hex(4))).fetchone()[0]
    app = c.execute("INSERT INTO applications (user_id, job_id) VALUES (%s, %s) RETURNING id", (uid, job)).fetchone()[0]
    c.execute("UPDATE applications SET payload_hash = %s WHERE id = %s", (HASH, app))
    for s in _path_to(state)[1:]:
        _move(c, app, s)
    approval = None
    if state == "approved":
        approval = c.execute(
            "INSERT INTO approval_records (user_id, application_id, payload_hash, payload, runner_device_id, expires_at, "
            "signature, key_id) VALUES (%s, %s, %s, '{}', %s, %s, 'sig', 'k') RETURNING id",
            (uid, app, HASH, dev, datetime.now(UTC) + timedelta(minutes=30))).fetchone()[0]
    return {"user": uid, "device": dev, "app": app, "approval": approval}


def _begin(a: dict[str, Any]) -> int | None:
    try:
        with _conn() as c:
            return c.execute("SELECT begin_submit(%s, %s, %s, %s, 'approved_submission')",
                             (a["app"], a["approval"], HASH, a["device"])).fetchone()[0]
    except psycopg.Error as e:
        if e.sqlstate == "LN003":
            return None
        raise


# ---------------------------------------------------------------------------


@settings(max_examples=25, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(st.integers(min_value=2, max_value=8))
def prop_no_two_sends(attempts: int) -> None:
    """However many runners race to submit one approval, exactly one intent is written."""

    with _conn() as c:
        a = make_application(c)
    barrier = threading.Barrier(attempts)
    results: list[int | None] = []
    lock = threading.Lock()

    def go() -> None:
        barrier.wait()
        r = _begin(a)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=go) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    won = [r for r in results if r is not None]
    assert won == [1], results
    with _conn() as c:
        assert c.execute("SELECT count(*) FROM submit_intents WHERE application_id = %s", (a["app"],)).fetchone()[0] == 1


@settings(max_examples=40, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(st.integers(min_value=-3, max_value=6).filter(lambda f: f != 1), st.integers(min_value=1, max_value=4))
def prop_stale_fence_rejected(stale: int, repeats: int) -> None:
    """Only the current fencing token can record an outcome, and only once."""

    with _conn() as c:
        a = make_application(c)
    assert _begin(a) == 1
    with _conn() as c:
        try:
            c.execute("SELECT record_submit_outcome(%s, %s, NULL, '')", (a["app"], stale))
            raise AssertionError("a stale fence recorded an outcome")
        except psycopg.Error as e:
            assert e.sqlstate == "LN004", e
        results = [c.execute("SELECT record_submit_outcome(%s, 1, NULL, '')", (a["app"],)).fetchone()[0]
                   for _ in range(repeats)]
        assert results[0] == "recorded" and all(r == "duplicate" for r in results[1:]), results
        n = c.execute("SELECT count(*) FROM outcome_events WHERE application_id = %s AND fence = 1", (a["app"],)).fetchone()[0]
        assert n == 1


@settings(max_examples=20, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(st.sampled_from(["approved", "in_review", "submitting", "drafted"]))
def prop_uncertain_is_never_retried(target: str) -> None:
    """Once a submission is uncertain, nothing can arm, submit or rewind it."""

    with _conn() as c:
        a = make_application(c)
    assert _begin(a) == 1
    with _conn() as c:
        assert c.execute("SELECT mark_submission_uncertain(%s, 'test')", (a["app"],)).fetchone()[0]
        try:
            _move(c, a["app"], target)
            raise AssertionError(f"submission_uncertain moved to {target}")
        except psycopg.Error as e:
            assert e.sqlstate.startswith("LN"), e
    assert _begin(a) is None


_STATES = [s.value for s in ApplicationState]


@settings(max_examples=120, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(st.sampled_from(_STATES), st.sampled_from(_STATES))
def prop_lifecycle_matches_the_spec(src: str, dst: str) -> None:
    """The database accepts a state change if and only if the shared lifecycle table allows it."""

    try:
        _path_to(src)
    except ValueError:
        return
    with _conn() as c:
        a = make_application(c, src)
        allowed = can_transition(ApplicationState(src), ApplicationState(dst))
        try:
            _move(c, a["app"], dst)
            accepted = True
        except psycopg.Error:
            accepted = False
    assert accepted == allowed or src == dst, (src, dst, accepted, allowed)


_text = st.text(min_size=0, max_size=40)


@settings(max_examples=200, deadline=None, database=None)
@given(st.dictionaries(st.from_regex(r"fk_[0-9a-f]{12}", fullmatch=True), _text, min_size=1, max_size=8), st.data())
def prop_any_change_breaks_the_approval(answers: dict[str, str], data: st.DataObject) -> None:
    """Changing any single answer changes the payload hash; reordering never does."""

    def payload(ans: dict[str, str]) -> dict[str, Any]:
        return {"application_id": "app", "profile_version_id": "pv", "destination": "lab",
                "answers": [{"field_key": k, "value": v, "fact_ids": []} for k, v in ans.items()],
                "documents": [], "consents": []}

    base = payload_hash(payload(answers))
    shuffled = dict(data.draw(st.permutations(list(answers.items()))))
    assert payload_hash(payload(shuffled)) == base
    key = data.draw(st.sampled_from(sorted(answers)))
    # Unicode is compared after NFC normalization, on purpose: "é" typed two ways is one answer.
    new = data.draw(_text.filter(lambda v: unicodedata.normalize("NFC", v) != unicodedata.normalize("NFC", answers[key])))
    assert payload_hash(payload({**answers, key: new})) != base


PROPERTIES: list[tuple[str, Callable[[], None], int]] = [
    ("No two sends: concurrent runners racing one approval write exactly one intent", prop_no_two_sends, 25),
    ("A stale fencing token never records an outcome; the current one records once", prop_stale_fence_rejected, 40),
    ("An uncertain submission is never armed, submitted or rewound", prop_uncertain_is_never_retried, 20),
    ("The database accepts exactly the lifecycle transitions the spec allows", prop_lifecycle_matches_the_spec, 120),
    ("Any single changed answer changes the approved payload hash; order never does", prop_any_change_breaks_the_approval, 200),
]


def run_properties() -> list[dict[str, Any]]:
    out = []
    for name, fn, n in PROPERTIES:
        try:
            fn()
            out.append({"name": name, "examples": n, "passed": True})
        except Exception as exc:  # noqa: BLE001 - a failing property is a published result
            out.append({"name": name, "examples": n, "passed": False, "detail": str(exc)[:400]})
    return out
