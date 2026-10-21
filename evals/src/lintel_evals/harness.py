"""A real stack for end-to-end tests: Postgres, the API, Lintel Lab and a paired Local Runner.

Nothing is mocked. The API runs as a subprocess against a fresh test database, the Lab serves the
forms, and the runner is the shipped `lintel` command with a headless browser. The crash suite
kills that runner at named points of the submit sequence and reads the result back from the
database and from the Lab's own record of what it received.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[3]
TEST_DSN = os.environ.get("LINTEL_TEST_DATABASE_URL", "postgresql+psycopg://lintel@127.0.0.1:5433/lintel_test")
PASSWORD = "lintel-test-2026"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(fn: Callable[[], Any], timeout: float = 30.0, every: float = 0.3, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(every)
    raise TimeoutError(f"timed out waiting for {what} (last: {last!r})")


def reset_database(dsn: str = TEST_DSN, env: dict[str, str] | None = None) -> None:
    """Drop everything in the test database and apply the migrations from scratch."""

    with psycopg.connect(dsn.replace("+psycopg", ""), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    env = {**(env or os.environ), "LINTEL_DATABASE_URL": dsn}
    subprocess.run([sys.executable, "-m", "lintel_api.cli", "migrate"], env=env, check=True, cwd=ROOT,
                   stdout=subprocess.DEVNULL)


def owner_conn(dsn: str = TEST_DSN) -> psycopg.Connection:
    """A connection as the database owner, outside row-level security, for assertions."""

    return psycopg.connect(dsn.replace("+psycopg", ""), autocommit=True)


@dataclass
class Stack:
    workdir: Path
    dsn: str = TEST_DSN
    uncertain_after_seconds: int = 6
    lab_port: int = field(default_factory=free_port)
    api_port: int = field(default_factory=free_port)
    procs: list[subprocess.Popen] = field(default_factory=list)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def lab_url(self) -> str:
        return f"http://127.0.0.1:{self.lab_port}"

    @property
    def lab_state(self) -> Path:
        return self.workdir / "lab" / "submissions.json"

    def api_env(self) -> dict[str, str]:
        return {
            **os.environ,
            "LINTEL_ENV": "development",
            "LINTEL_DATABASE_URL": self.dsn,
            "LINTEL_DATA_DIR": str(self.workdir / "api-data"),
            "LINTEL_LAB_BASE_URL": self.lab_url,
            "LINTEL_PUBLIC_API_URL": self.api_url,
            "LINTEL_LLM_PROVIDER": "offline",
            "LINTEL_EMBEDDED_WORKER": "1",
            "LINTEL_SUBMIT_UNCERTAIN_AFTER_SECONDS": str(self.uncertain_after_seconds),
            "LINTEL_RUN_LEASE_SECONDS": "20",
        }

    def _spawn(self, name: str, args: list[str], env: dict[str, str]) -> subprocess.Popen:
        log = open(self.workdir / f"{name}.log", "w")  # noqa: SIM115 - closed with the process
        p = subprocess.Popen(args, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        return p

    def start(self) -> Stack:
        self.workdir.mkdir(parents=True, exist_ok=True)
        reset_database(self.dsn, self.api_env())
        self._spawn("lab", [sys.executable, "-m", "uvicorn", "lintel_lab.server:app", "--port", str(self.lab_port),
                            "--log-level", "warning"], {**os.environ, "LINTEL_LAB_STATE": str(self.lab_state)})
        self._spawn("api", [sys.executable, "-m", "uvicorn", "lintel_api.app:app", "--port", str(self.api_port),
                            "--log-level", "warning"], self.api_env())
        for url in (f"{self.lab_url}/lab", f"{self.api_url}/health"):
            wait_until(lambda u=url: _ok(u), 60, what=url)
        return self

    def stop(self) -> None:
        for p in self.procs:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, 15)
        for p in self.procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(10)
        self.procs.clear()

    def lab_submissions(self) -> list[dict[str, Any]]:
        return httpx.get(f"{self.lab_url}/lab/submissions").json()

    def account(self, email: str) -> Account:
        return Account(self, email)


def _ok(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@contextlib.contextmanager
def running_stack(**kw: Any) -> Iterator[Stack]:
    with tempfile.TemporaryDirectory(prefix="lintel-stack-") as d:
        s = Stack(Path(d), **kw).start()
        try:
            yield s
        finally:
            s.stop()


# ---------------------------------------------------------------------------
# A person using the product through the same API the web app uses
# ---------------------------------------------------------------------------


class Account:
    def __init__(self, stack: Stack, email: str):
        self.stack = stack
        self.email = email
        self.c = httpx.Client(base_url=stack.api_url, timeout=60)
        self.device_id: str | None = None
        self.token: str | None = None
        self.home = stack.workdir / f"runner-{email.split('@')[0]}"
        self.runs = 0

    # -- setup ---------------------------------------------------------------

    def create(self, *, companies: tuple[str, ...] = ("acme",)) -> Account:
        """A demo-shaped account: confirmed résumé facts, targets, filters, Lab companies watched."""

        env = self.stack.api_env()
        subprocess.run([sys.executable, "-m", "lintel_api.cli", "demo", "--email", self.email, "--password", PASSWORD],
                       env=env, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        self.login()
        keep = set(companies)
        for co in self.get("/watchlist"):
            if co["board_name"] not in keep:
                self.c.delete(f"/watchlist/{co['id']}")
        return self

    def login(self) -> None:
        r = self.c.post("/auth/login", json={"email": self.email, "password": PASSWORD})
        r.raise_for_status()

    def get(self, path: str, **kw: Any) -> Any:
        r = self.c.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Any = None, ok: bool = True) -> httpx.Response:
        r = self.c.post(path, json=json)
        if ok and r.status_code >= 400:
            raise AssertionError(f"POST {path} -> {r.status_code} {r.text[:400]}")
        return r

    # -- applications ----------------------------------------------------------

    def app_id(self, title: str, timeout: float = 60) -> str:
        def find() -> str | None:
            return next((a["id"] for a in self.get("/applications") if a["job"]["title"] == title), None)

        return wait_until(find, timeout, what=f"application for {title}")

    def detail(self, aid: str) -> dict[str, Any]:
        return self.get(f"/applications/{aid}")

    def state(self, aid: str) -> str:
        return self.detail(aid)["application"]["state"]

    def wait_state(self, aid: str, states: str | tuple[str, ...], timeout: float = 60) -> str:
        want = (states,) if isinstance(states, str) else states
        return wait_until(lambda: (s := self.state(aid)) in want and s, timeout, what=f"state in {want}")

    def to_drafted(self, aid: str) -> dict[str, Any]:
        """Gate 1 go, answer what only the person can answer, confirm grounding, wait for drafts."""

        if self.state(aid) in ("imported", "fit_review"):
            self.wait_state(aid, "fit_review")
            self.post(f"/applications/{aid}/decide", {"go": True})
        self.wait_state(aid, ("grounding", "drafted"))
        if self.state(aid) == "grounding":
            self.answer_open(aid, settle=False)
            self.post(f"/applications/{aid}/grounding/confirm")
        self.wait_state(aid, "drafted", 90)
        self.answer_open(aid)
        return self.detail(aid)

    def answer_open(self, aid: str, *, settle: bool = True) -> None:
        """Answer every question waiting on the person, then tick consents and accept checked drafts."""

        for dr in self.detail(aid)["drafts"]:
            if dr["decision"] == "ask_user" and dr["status"] != "ready" and dr["category"] != "consent":
                self.post(f"/applications/{aid}/answers/{dr['field_key']}", {"value": answer_for(dr), "scope": "application"})
        if not settle:
            return
        wait_until(lambda: all(x["status"] != "pending" for x in self.detail(aid)["drafts"]), 90, what="drafts")
        d = self.detail(aid)
        for dr in d["drafts"]:
            if dr["category"] == "consent" and dr["value"] is not True:
                self.post(f"/applications/{aid}/consents/{dr['field_key']}", {"value": True})
            elif dr["status"] == "blocked":
                self.post(f"/applications/{aid}/drafts/{dr['field_key']}/accept-partial")
        for v in d["variants"]:
            if v["status"] == "proposed":
                self.post(f"/applications/{aid}/variants/{v['id']}/approve")

    def fill(self, aid: str, timeout: float = 240, **runner_env: str) -> None:
        """Ask for a fill and keep a runner going; answer new questions from the live form and resume."""

        if self.token is None:
            self.pair()
        self.post(f"/applications/{aid}/fill")
        proc = self.background_runner(**runner_env)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                d = self.detail(aid)
                if d["application"]["state"] != "filling":
                    return
                run = next((r for r in d["runs"] if r["state"] == "waiting_user"), None)
                if run:
                    self.answer_open(aid)
                    self.post(f"/runs/{run['id']}/resume")
                time.sleep(1)
            raise TimeoutError(f"fill still running after {timeout}s")
        finally:
            stop(proc)

    def background_runner(self, idle_exit: float = 60, **extra: str) -> subprocess.Popen:
        if self.token is None:
            self.pair()
        self.runs += 1
        log = open(self.home / f"runner-{self.runs}.log", "w")  # noqa: SIM115 - owned by the process
        return subprocess.Popen([sys.executable, "-m", "lintel_runner.cli", "start", "--headless", "--idle-exit", str(idle_exit)],
                                env=self.runner_env(**extra), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

    def approve(self, aid: str, mode: str | None = None) -> dict[str, Any]:
        d = self.detail(aid)
        body: dict[str, Any] = {"payload_hash": d["application"]["payload_hash"]}
        if mode:
            body["mode"] = mode
        return self.post(f"/applications/{aid}/approve", body).json()

    # -- the Local Runner --------------------------------------------------------

    def pair(self) -> None:
        start = httpx.post(f"{self.stack.api_url}/runner/pair/start", json={"name": "Test runner", "platform": "Linux"}).json()
        self.post("/devices/pair", {"user_code": start["user_code"]})
        r = httpx.post(f"{self.stack.api_url}/runner/pair/poll", json={"device_code": start["device_code"]}).json()
        assert r["status"] == "approved", r
        self.device_id, self.token = r["device_id"], r["token"]
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "config.json").write_text(json.dumps({
            "api_url": self.stack.api_url, "device_id": self.device_id, "device_name": "Test runner",
            "public_key_pem": r["public_key_pem"], "extra": {},
        }))

    def runner_env(self, **extra: str) -> dict[str, str]:
        return {
            **os.environ,
            "LINTEL_RUNNER_HOME": str(self.home),
            "LINTEL_API_URL": self.stack.api_url,
            "LINTEL_DEVICE_TOKEN": self.token or "",
            "LINTEL_HEADLESS": "1",
            "LINTEL_OUTCOME_TIMEOUT": "6",
            **extra,
        }

    def run_runner(self, timeout: float = 150, idle_exit: float = 15, **extra: str) -> subprocess.CompletedProcess:
        """One run with the shipped runner command: claim, execute, exit (or exit when there's no work)."""

        if self.token is None:
            self.pair()
        self.runs += 1
        log = self.home / f"runner-{self.runs}.log"
        with open(log, "w") as out:
            p = subprocess.run([sys.executable, "-m", "lintel_runner.cli", "start", "--headless", "--once",
                                "--idle-exit", str(idle_exit)],
                               env=self.runner_env(**extra), cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
        p.stdout = log.read_text()
        return p

    def journal(self) -> list[dict[str, Any]]:
        p = self.home / "journal.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def sweep(self) -> None:
        """Run the scheduler once so expired leases and silent submits are resolved now."""

        subprocess.run([sys.executable, "-c", "from lintel_api.worker import scheduler_tick; scheduler_tick()"],
                       env=self.stack.api_env(), check=True, cwd=ROOT, stdout=subprocess.DEVNULL)


def stop(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()


def answer_for(draft: dict[str, Any]) -> Any:
    """What a careful person would answer for a question Lintel must not guess."""

    label = draft["label"].lower()
    options = draft.get("options") or []

    def pick(*words: str) -> str:
        for w in words:
            for o in options:
                if o["label"].lower().startswith(w):
                    return o["value"]
        return options[0]["value"]

    if draft["field_type"] in ("checkbox",):
        return True
    if options:
        if "sponsor" in label:
            return pick("yes")
        if "authori" in label:
            return pick("no")
        if draft["field_type"] in ("multiselect", "checkbox_group"):
            return [options[0]["value"]]
        return pick("decline", "i don", "prefer not")
    if "hear" in label:
        return "Company careers page"
    if "salary" in label or "compensation" in label:
        return "Open to discussing"
    if "start" in label or "notice" in label:
        return "Four weeks"
    return "Not applicable"
