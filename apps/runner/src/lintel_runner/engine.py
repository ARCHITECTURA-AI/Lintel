"""Run execution: a deterministic workflow with bounded planning inside one run.

The fill loop is a small LangGraph state machine (observe -> act -> observe ..., advance a step,
pause or finish). It is not the source of truth for state, approvals or locks: Postgres is.
Every action passes the policy gate, is verified by reading the value back, and is logged as a
hash and a length.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from lintel_schemas import (
    CanonicalPayload,
    FieldType,
    FormField,
    RunAssignment,
    RunKind,
    SupportMode,
)
from lintel_trust import (
    SignatureError,
    load_public_key,
    normalize_value,
    payload_hash,
    verify_approval,
    verify_fill_grant,
)
from playwright.sync_api import Page

from . import adapters
from .browser import Browser
from .client import Api, ApiError
from .config import RunnerConfig
from .forms import INIT_SCRIPT, PageRead, file_hashes, parse_read, read_page
from .gate import Action, Denied, PolicyGate
from .steps import Journal, StepLog

log = logging.getLogger("lintel.runner")
CRASH_AT = os.environ.get("LINTEL_RUNNER_CRASH_AT", "")


def _crash(point: str) -> None:
    """Test hook for the crash suite: kill the runner at a named step of the submit sequence."""

    if point == CRASH_AT:
        log.error("crash hook: exiting at %s", point)
        os._exit(137)


class RunEnded(Exception):
    pass


class Heartbeat(threading.Thread):
    def __init__(self, cfg: RunnerConfig, token: str, run_id: str, interval: float = 10.0):
        super().__init__(daemon=True)
        self.api = Api(cfg.api_url, token)
        self.run_id = run_id
        self.interval = interval
        self.cancel = threading.Event()
        self.stopped = threading.Event()
        self.app_state: str | None = None

    def run(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                r = self.api.post(f"/runner/runs/{self.run_id}/heartbeat")
                self.app_state = r.get("application_state")
                if r.get("cancel"):
                    self.cancel.set()
            except ApiError:
                self.cancel.set()
            except Exception:  # noqa: BLE001 - network blips are retried next tick
                pass


class FillState(TypedDict, total=False):
    phase: str
    read: Any
    pending: list
    attempts: dict
    no_progress: int
    reason: str
    detail: str


class RunExecutor:
    def __init__(self, cfg: RunnerConfig, token: str, api: Api, browser: Browser, assignment: RunAssignment):
        self.cfg = cfg
        self.token = token
        self.api = api
        self.browser = browser
        self.a = assignment
        self.steps = StepLog(api, assignment.run_id)
        self.journal = Journal(cfg.journal_path)
        self.public_key = load_public_key(cfg.public_key_pem) if cfg.public_key_pem else None
        self.page: Page | None = None
        self.heartbeat: Heartbeat | None = None
        self.started = time.monotonic()
        self.resume_requested = threading.Event()
        self.window_closed = threading.Event()
        self.adopt_requested = threading.Event()
        self.restore_requested = threading.Event()
        self.fence: int | None = None
        self.clicked = False
        self._current_model = None
        self.last_diffs: list[dict[str, Any]] = []
        self.gate = self._gate()

    # ------------------------------------------------------------------ setup

    def _gate(self) -> PolicyGate:
        return PolicyGate(kind=self.a.kind, mode=self.a.support_mode, payload=self.a.payload,
                          allowed_hosts=self.a.allowed_hosts, permitted_paths=self.a.permitted_paths)

    def _limits(self, key: str, default: int) -> int:
        return int(self.a.limits.get(key, default))

    def _start_heartbeat(self) -> None:
        if self.heartbeat:
            self.heartbeat.stopped.set()
        self.heartbeat = Heartbeat(self.cfg, self.token, self.a.run_id)
        self.heartbeat.start()

    def _check_cancel(self) -> None:
        # Cancellation is checked before every consequential action.
        if self.heartbeat and self.heartbeat.cancel.is_set():
            raise RunEnded("cancelled")
        if self.window_closed.is_set():
            raise RunEnded("window closed")

    def _pump(self, ms: int = 300) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001 - page closed
            self.window_closed.set()

    # ------------------------------------------------------------------ entry

    def execute(self) -> None:
        self.browser.set_allowlist(self.a.allowed_hosts)
        self._start_heartbeat()
        try:
            if self.a.kind == RunKind.read_form:
                self._read_form()
            elif self.a.kind == RunKind.fill:
                self._verify_grant()
                self._fill()
            elif self.a.kind == RunKind.submit:
                self._verify_approval()
                self._submit()
        except RunEnded as e:
            self.steps.add("end", verification="skipped", detail=str(e))
            self.steps.flush()
            if str(e) not in ("cancelled", "completed"):
                self._fail(str(e))
        except Denied as e:
            self.steps.add("gate", verification="blocked", detail=str(e))
            self._fail(f"policy gate refused an action: {e}")
        except SignatureError as e:
            self.steps.add("verify_signature", verification="blocked", detail=str(e))
            self._fail(str(e))
        except ApiError as e:
            self._fail(f"{e.code}: {e.message}")
        finally:
            if self.heartbeat:
                self.heartbeat.stopped.set()
            try:
                self.steps.flush()
            except ApiError:
                pass

    def _fail(self, reason: str) -> None:
        try:
            self.steps.flush()
        except ApiError:
            pass
        try:
            self.api.post(f"/runner/runs/{self.a.run_id}/fail", json={"reason": reason[:300]})
        except ApiError as exc:
            log.warning("couldn't report the failure: %s", exc)

    def _complete(self, summary: str) -> None:
        self.steps.flush()
        self.api.post(f"/runner/runs/{self.a.run_id}/complete", json={"summary": summary})

    # ------------------------------------------------------------------ signatures

    def _verify_grant(self) -> None:
        if self.a.payload is None or self.a.fill_grant is None or self.public_key is None:
            raise SignatureError("no signed payload for this fill")
        local = payload_hash(self.a.payload)
        if local != self.a.payload_hash:
            raise SignatureError("the payload does not match its hash")
        verify_fill_grant(self.public_key, self.a.fill_grant, payload_hash=local, runner_device_id=self.cfg.device_id)
        self.steps.add("verify_signature", detail="fill grant verified")

    def _verify_approval(self) -> None:
        if self.a.payload is None or self.a.approval is None or self.public_key is None:
            raise SignatureError("no signed approval for this submission")
        local = payload_hash(self.a.payload)
        if local != self.a.approval.payload_hash:
            raise SignatureError("the payload does not match the approval")
        verify_approval(self.public_key, self.a.approval, payload_hash=local, runner_device_id=self.cfg.device_id)
        self.steps.add("verify_signature", detail="approval verified")

    # ------------------------------------------------------------------ navigation

    def _open(self, *, fresh: bool = False) -> Page:
        page = self.browser.existing_page(self.a.application_id)
        target = self.a.apply_url
        if page is not None and not fresh:
            same = page.url.split("?")[0].rstrip("/") == target.split("?")[0].rstrip("/")
            if same:
                self.page = page
                self._bind(page)
                return page
        page = self.browser.page_for(self.a.application_id)
        self.page = page
        self._bind(page)
        self._check_cancel()
        self.gate.check(Action("navigate", target=target), None)
        page.goto(target, wait_until="domcontentloaded")
        self.steps.add("navigate", detail=target.split("?")[0][-120:])
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        return page

    def _bind(self, page: Page) -> None:
        if getattr(page, "_lintel_bound", False):
            return
        page.expose_binding("lintelGuardCheck", lambda source, arg: self._guard_check(arg or {}))
        page.expose_binding("lintelGuardAdopt", lambda source: self.adopt_requested.set())
        page.expose_binding("lintelGuardRestore", lambda source: self.restore_requested.set())
        page.expose_binding("lintelResume", lambda source: self.resume_requested.set())
        page.expose_binding("lintelSubmitAnyway", lambda source: self._submit_anyway())
        page.on("close", lambda _p: self.window_closed.set())
        page._lintel_bound = True  # type: ignore[attr-defined]
        # Scripts for pages that loaded before this run.
        try:
            page.add_script_tag(content=INIT_SCRIPT)
        except Exception:  # noqa: BLE001
            pass
        for name in ("banner.js", "guard.js"):
            try:
                page.add_script_tag(path=str(Path(__file__).parent / "js" / name))
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ read form

    def _blocker(self, pr: PageRead) -> tuple[str, str] | None:
        if pr.login_wall:
            return "login", "The site asks you to sign in."
        if pr.session_expired:
            return "session_expired", "The page session expired."
        if pr.dialog:
            return "modal", pr.dialog[:160]
        if pr.captcha and not pr.visible_fields:
            return "captcha", "A bot challenge covers the page."
        return None

    def _read_form(self) -> None:
        page = self._open(fresh=True)
        pr = read_page(page)
        self.steps.add("read_form", detail=f"{len(pr.model.fields)} fields, page {pr.model.page_version}")
        self.api.post(f"/runner/runs/{self.a.run_id}/form", json=pr.model.model_dump(mode="json"))
        self._complete("form read")

    # ------------------------------------------------------------------ fill

    def _report_form(self, pr: PageRead) -> dict[str, Any]:
        r = self.api.post(f"/runner/runs/{self.a.run_id}/form", json=pr.model.model_dump(mode="json"))
        new = r.get("assignment")
        if new:
            fresh = RunAssignment.model_validate(new)
            if fresh.payload_hash != self.a.payload_hash:
                # The page differed from the cloud's expectations; the cloud re-issued a signed payload.
                self.a = fresh
                if self.a.kind == RunKind.fill:
                    self._verify_grant()
                self.gate = self._gate()
                self.steps.add("payload_reissued", detail="form reconciled with the live page")
        return r

    def _wanted(self) -> dict[str, tuple[str, Any]]:
        """field_key -> (kind, value) for everything the payload puts on the page."""

        p: CanonicalPayload = self.a.payload
        out: dict[str, tuple[str, Any]] = {a.field_key: ("answer", a.value) for a in p.answers}
        out.update({c.field_key: ("consent", c.value) for c in p.consents})
        for d in p.documents:
            if d.field_key:
                out[d.field_key] = ("document", d.sha256)
        return out

    def _matches(self, pr: PageRead, key: str, kind: str, value: Any, hashes: dict[str, str]) -> bool:
        lf = pr.live.get(key)
        if lf is None:
            return False
        f = lf.field
        if kind == "document":
            css = f.locator.css if f.locator else ""
            return hashes.get(css) == value or any(v == value for k, v in hashes.items() if k.endswith(css.lstrip("#")))
        return normalize_value(f.type, value) == normalize_value(f.type, lf.value)

    def _apply(self, f: FormField, kind: str, value: Any) -> None:
        css = f.locator.css if f.locator else None
        page = self.page
        if kind == "document":
            path = self._document(value)
            self.gate.check(Action("upload", f.field_key, target=value), self._current_model)
            page.set_input_files(css, str(path))
            self.steps.add("upload", field_key=f.field_key, value=value)
            return
        action = {FieldType.select: "select", FieldType.radio: "check", FieldType.checkbox: "check",
                  FieldType.multiselect: "select"}.get(f.type, "fill")
        self.gate.check(Action(action, f.field_key, value), self._current_model)
        if f.type in (FieldType.text, FieldType.textarea, FieldType.email, FieldType.tel, FieldType.url,
                      FieldType.number, FieldType.date):
            page.fill(css, "" if value is None else str(value))
        elif f.type == FieldType.select:
            page.select_option(css, value=str(value))
        elif f.type == FieldType.radio:
            page.check(f'{css}[value="{value}"]')
        elif f.type == FieldType.checkbox:
            page.set_checked(css, bool(value))
        elif f.type == FieldType.multiselect:
            values = value if isinstance(value, list) else [value]
            if css and css.startswith("select"):
                page.select_option(css, value=[str(v) for v in values])
            else:
                for opt in f.options:
                    page.set_checked(f'{css}[value="{opt.value}"]', opt.value in values)
        self.steps.add(action, field_key=f.field_key, value=value)

    def _document(self, sha256: str) -> Path:
        meta = next((d for d in self.a.documents if d["sha256"] == sha256), None)
        if meta is None:
            raise Denied("document is not on the approved list")
        self.cfg.docs_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(meta.get("filename") or "resume.pdf").suffix or ".pdf"
        path = self.cfg.docs_dir / f"{sha256}{ext}"
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            data = self.api.get(meta["url"])
            if hashlib.sha256(data).hexdigest() != sha256:
                raise Denied("downloaded document does not match its approved hash")
            path.write_bytes(data)
        return path

    def _plan(self, pr: PageRead) -> list[tuple[FormField, str, Any]]:
        wanted = self._wanted()
        hashes = file_hashes(self.page) if any(k == "document" for k, _ in wanted.values()) else {}
        out = []
        for key, (kind, value) in wanted.items():
            lf = pr.live.get(key)
            if lf is None or not lf.field.visible:
                continue
            if self._matches(pr, key, kind, value, hashes):
                continue
            if kind == "consent" and not value:
                continue
            out.append((lf.field, kind, value))
        return out

    def _build_fill_graph(self):
        max_actions = self._limits("max_actions", 50)
        max_recoveries = self._limits("max_recoveries", 2)
        max_minutes = self._limits("max_active_minutes", 15)

        def observe(state: FillState) -> FillState:
            self._check_cancel()
            pr = read_page(self.page)
            self._current_model = pr.model
            blocker = self._blocker(pr)
            if blocker:
                return {**state, "phase": "pause", "reason": blocker[0], "detail": blocker[1], "read": pr}
            if state.get("phase") == "start":
                r = self._report_form(pr)
                if r.get("blocking"):
                    return {**state, "phase": "pause", "reason": "missing_fact",
                            "detail": f"{len(r['blocking'])} new question(s) on the live form", "read": pr}
                pr = read_page(self.page)
                self._current_model = pr.model
            pending = self._plan(pr)
            if time.monotonic() - self.started > max_minutes * 60:
                return {**state, "phase": "pause", "reason": "paused", "read": pr}
            if pending:
                return {**state, "phase": "act", "pending": pending, "read": pr}
            unfilled = [k for k, (kind, v) in self._wanted().items()
                        if k in pr.live and not pr.live[k].field.visible and not (kind == "consent" and not v)]
            missing = [k for k in self._wanted() if k not in pr.live]
            if (unfilled or missing) and pr.has_next:
                return {**state, "phase": "advance", "read": pr}
            return {**state, "phase": "finish", "read": pr}

        def act(state: FillState) -> FillState:
            f, kind, value = state["pending"][0]
            attempts = dict(state.get("attempts") or {})
            if self.steps.actions >= max_actions:
                return {**state, "phase": "pause", "reason": "no_progress", "detail": "action budget reached"}
            if attempts.get(f.field_key, 0) > max_recoveries:
                return {**state, "phase": "pause", "reason": "validation",
                        "detail": f"“{f.label}” didn't take the approved value"}
            attempts[f.field_key] = attempts.get(f.field_key, 0) + 1
            self._check_cancel()
            self._apply(f, kind, value)
            # Verify after every action.
            pr = read_page(self.page)
            self._current_model = pr.model
            hashes = file_hashes(self.page) if kind == "document" else {}
            ok = self._matches(pr, f.field_key, kind, value, hashes)
            invalid = pr.live.get(f.field_key).invalid if pr.live.get(f.field_key) else False
            self.steps.add("verify", field_key=f.field_key, value=value,
                           verification="ok" if ok and not invalid else "mismatch",
                           detail="site flagged the value as invalid" if invalid else "")
            if invalid and attempts[f.field_key] > max_recoveries:
                return {**state, "phase": "pause", "reason": "validation", "detail": f"The site rejected “{f.label}”."}
            return {**state, "phase": "observe", "attempts": attempts, "no_progress": 0 if ok else state.get("no_progress", 0) + 1}

        def advance(state: FillState) -> FillState:
            self._check_cancel()
            self.gate.check(Action("next_step"), self._current_model)
            btn = self.page.locator("form button[type=button]").filter(has_text="Next")
            if btn.count() == 0:
                btn = self.page.get_by_role("button", name="Continue")
            btn.first.click()
            self.steps.add("click", detail="next step")
            self._pump(300)
            np = state.get("no_progress", 0) + 1
            if np > 3:
                return {**state, "phase": "pause", "reason": "no_progress", "no_progress": np}
            return {**state, "phase": "observe", "no_progress": np}

        def route(state: FillState) -> str:
            return {"observe": "observe", "act": "act", "advance": "advance"}.get(state.get("phase", ""), END)

        g = StateGraph(FillState)
        g.add_node("observe", observe)
        g.add_node("act", act)
        g.add_node("advance", advance)
        g.set_entry_point("observe")
        g.add_conditional_edges("observe", route, {"act": "act", "advance": "advance", "observe": "observe", END: END})
        g.add_conditional_edges("act", route, {"observe": "observe", "act": "act", END: END})
        g.add_conditional_edges("advance", route, {"observe": "observe", END: END})
        return g.compile()

    def _final_verify(self) -> list[str]:
        pr = read_page(self.page)
        hashes = file_hashes(self.page)
        bad = []
        for key, (kind, value) in self._wanted().items():
            if kind == "consent" and not value:
                continue
            ok = self._matches(pr, key, kind, value, hashes)
            label = pr.live[key].field.label if key in pr.live else self.a.field_labels.get(key, key)
            self.steps.add("verify", field_key=key, value=value, verification="ok" if ok else "mismatch",
                           detail="" if ok else "value differs or field missing")
            if not ok:
                bad.append(label)
        return bad

    def _fill(self) -> None:
        self._open()
        self.browser.show_banner(self.page, "filling", len(self.a.payload.answers) if self.a.payload else 0)
        graph = self._build_fill_graph()
        state: FillState = {"phase": "start", "attempts": {}, "no_progress": 0}
        while True:
            state = graph.invoke({**state, "phase": state.get("phase") or "start"}, {"recursion_limit": 400})
            if state.get("phase") == "pause":
                self._pause(state.get("reason", "no_progress"), state.get("detail", ""))
                state = {"phase": "start", "attempts": {}, "no_progress": 0}
                continue
            break
        bad = self._final_verify()
        if bad:
            self._pause("validation", "Not filled as approved: " + ", ".join(bad[:4]))
            bad = self._final_verify()
            if bad:
                raise RunEnded("values didn't stick: " + ", ".join(bad[:4]))
        pr = read_page(self.page)
        if pr.captcha:
            self.api.post(f"/runner/runs/{self.a.run_id}/form", json={**pr.model.model_dump(mode="json")})
        self.browser.show_banner(self.page, "filled")
        self._complete("filled and verified")

    # ------------------------------------------------------------------ waiting_user

    def _pause(self, reason: str, detail: str = "") -> None:
        """Waiting for the person. Resuming creates a new run that starts from a fresh read."""

        self.steps.add("pause", verification="skipped", detail=f"{reason}: {detail}"[:300])
        self.steps.flush()
        self.api.post(f"/runner/runs/{self.a.run_id}/waiting", json={"reason": reason, "detail": detail})
        titles = {
            "captcha": "Complete the CAPTCHA, then press Resume",
            "mfa": "Finish signing in, then press Resume",
            "login": "Sign in, then press Resume",
            "modal": "Close the dialog, then press Resume",
            "session_expired": "Reload the page, then press Resume",
            "missing_fact": "Answer the new questions in Lintel, then press Resume",
            "validation": "Fix the highlighted field, then press Resume",
            "paused": "Paused after 15 minutes. Press Resume to continue",
            "no_progress": "Lintel stopped making progress. Check the page, then press Resume",
        }
        self.browser.show_banner(self.page, "paused", titles.get(reason, "Complete this step, then press Resume"), detail)
        self.resume_requested.clear()
        if reason in os.environ.get("LINTEL_TEST_HUMAN_RESOLVES", "").split(","):
            self._test_person_resolves(reason)
        deadline = time.monotonic() + 60 * 60
        while not self.resume_requested.is_set():
            self._check_cancel()
            if time.monotonic() > deadline:
                raise RunEnded("waited an hour without a resume")
            self._pump(400)
            # the person may have resumed from the dashboard instead
            try:
                st = self.api.get(f"/runner/runs/{self.a.run_id}/status")
                if st["state"] != "waiting_user":
                    raise RunEnded("cancelled")
            except ApiError:
                pass
        new = RunAssignment.model_validate(self.api.post(f"/runner/runs/{self.a.run_id}/resume"))
        self.a = new
        self.steps.retarget(new.run_id)
        if self.heartbeat:
            self.heartbeat.stopped.set()
        self._start_heartbeat()
        if self.a.kind == RunKind.fill:
            self._verify_grant()
        elif self.a.kind == RunKind.submit:
            self._verify_approval()
        self.gate = self._gate()
        self.started = time.monotonic()
        self.steps.add("resume", detail="fresh read of the page")

    def _test_person_resolves(self, reason: str) -> None:
        """Test hook standing in for the person at the paused browser: they deal with it, then press Resume."""

        if reason == "modal":
            self.page.locator("[role=dialog] button").first.click()
        elif reason == "session_expired":
            self.page.reload(wait_until="domcontentloaded")
        self.resume_requested.set()

    # ------------------------------------------------------------------ the Submit Guard

    def _compare(self, pr: PageRead, hashes: dict[str, str]) -> list[dict[str, Any]]:
        diffs = []
        wanted = self._wanted()
        for key, (kind, value) in wanted.items():
            if self._matches(pr, key, kind, value, hashes):
                continue
            if kind == "consent" and not value and key in pr.live and not pr.live[key].value:
                continue
            lf = pr.live.get(key)
            label = lf.field.label if lf else self.a.field_labels.get(key, key)
            live = None
            if lf is not None:
                live = "(file attached)" if kind == "document" and lf.value else lf.value
            diffs.append({"field_key": key, "label": label,
                          "approved": "(approved file)" if kind == "document" else value, "live": live})
        # Anything typed into a field the approval doesn't cover would leave without approval.
        for key, lf in pr.live.items():
            if key in wanted or not lf.field.visible:
                continue
            empty = lf.value in (None, "", False, []) or (lf.field.type == FieldType.select and lf.value == "")
            if not empty:
                diffs.append({"field_key": key, "label": lf.field.label, "approved": "", "live": lf.value})
        return diffs

    def _guard_check(self, arg: dict[str, Any]) -> dict[str, Any]:
        trigger = arg.get("trigger", "click")
        if self.a.kind != RunKind.submit or self.a.approval is None:
            self.steps.add("guard_check", verification="blocked", detail="no approval yet")
            return {"ok": False, "unapproved": True,
                    "reasons": ["You haven't approved this payload in Lintel yet. Nothing was sent."]}
        if self.fence is not None:
            return {"ok": False, "reasons": ["This approval was already used for a click. Lintel never sends twice."]}
        try:
            self._check_cancel()
            # Bindings can't call back into the page, so the page sends its own reading.
            snapshot = arg.get("snapshot")
            if snapshot is None:
                return {"ok": False, "reasons": ["The Guard couldn't read the form. Nothing was sent."]}
            pr = parse_read(snapshot)
            diffs = self._compare(pr, arg.get("files") or {})
            if diffs:
                self.steps.add("guard_check", verification="blocked", detail=f"{len(diffs)} field(s) differ ({trigger})")
                self.last_diffs = diffs
                self.api.post(f"/runner/applications/{self.a.application_id}/guard-mismatch",
                              json={"diffs": [{"field_key": d["field_key"], "label": d["label"]} for d in diffs]})
                return {"ok": False, "diffs": diffs}
            local = payload_hash(self.a.payload)
            verify_approval(self.public_key, self.a.approval, payload_hash=local, runner_device_id=self.cfg.device_id)
            server = self.api.post(f"/runner/applications/{self.a.application_id}/guard-check",
                                   json={"approval_id": self.a.approval.approval_id, "payload_hash": local})
            if not server.get("ok"):
                self.steps.add("guard_check", verification="blocked", detail="; ".join(server.get("reasons", []))[:300])
                return {"ok": False, "reasons": server.get("reasons", [])}
            _crash("before_intent")
            # Write-ahead: the intent is recorded before the click is let through.
            r = self.api.post_once(f"/runner/applications/{self.a.application_id}/submit-intent",
                                   json={"approval_id": self.a.approval.approval_id, "payload_hash": local,
                                         "mode": self.a.support_mode.value})
            self.fence = int(r["fence"])
            self.journal.write(event="intent", application_id=self.a.application_id, fence=self.fence, payload_hash=local)
            self.steps.add("submit_intent", detail=f"fence {self.fence}")
            self.steps.flush()
            _crash("after_intent")
            self.gate.guard_passed = True
            return {"ok": True}
        except SignatureError as e:
            self.steps.add("guard_check", verification="blocked", detail=str(e))
            return {"ok": False, "reasons": [str(e)]}
        except ApiError as e:
            self.steps.add("guard_check", verification="blocked", detail=e.message[:200])
            return {"ok": False, "reasons": [e.message]}
        except RunEnded as e:
            return {"ok": False, "reasons": [f"Run ended: {e}"]}

    def _submit_anyway(self) -> bool:
        """The person submits outside the Guard. Lintel records it honestly."""

        try:
            self.api.post(f"/runner/applications/{self.a.application_id}/user-submitted", json={})
            self.steps.add("user_submitted", verification="skipped", detail="sent outside the Guard by the person")
            self.journal.write(event="user_submitted", application_id=self.a.application_id)
            return True
        except ApiError:
            return False

    def _submit(self) -> None:
        page = self._open()
        self.browser.show_banner(page, "info", "Checking the form against your approval", "")
        # Re-read the live page and repair any value from the approved payload before arming.
        graph = self._build_fill_graph()
        while True:
            state = graph.invoke({"phase": "observe", "attempts": {}, "no_progress": 0}, {"recursion_limit": 400})
            if state.get("phase") != "pause" or state.get("reason") == "captcha":
                break
            # After the person deals with it and resumes, repair the form again before arming.
            self._pause(state.get("reason", "no_progress"), state.get("detail", ""))
        self.steps.add("guard_armed", detail=self.a.support_mode.value)
        self.steps.flush()
        page.evaluate("() => { window.__lintelBypass = false; }")
        if self.a.support_mode == SupportMode.approved_submission:
            pr = read_page(page)
            if pr.captcha:
                # A bot challenge drops the destination to assisted fill; the person clicks.
                self.api.post(f"/runner/runs/{self.a.run_id}/form", json=pr.model.model_dump(mode="json"))
                self.a.support_mode = SupportMode.assisted_fill
                self.gate = self._gate()
            else:
                snapshot = page.evaluate("() => window.__lintelReadForm()")
                verdict = self._guard_check({"trigger": "lintel", "snapshot": snapshot, "files": file_hashes(page)})
                if not verdict.get("ok"):
                    self.browser.show_banner(page, "blocked", verdict)
                    raise RunEnded("guard blocked the approved submission")
                self.gate.check(Action("click_submit"), None)
                page.evaluate("() => { window.__lintelBypass = true; }")
                page.locator("form button[type=submit], form input[type=submit]").first.click()
                self.clicked = True
                self.steps.add("click", detail="final submit, once, after exact approval")
        self.browser.show_banner(page, "armed", self.a.support_mode.value)
        if os.environ.get("LINTEL_TEST_HUMAN_CLICK") == "1" and not self.clicked:
            # Test hooks standing in for the person: an optional edit in the browser after approval,
            # then a real click on the site's Submit, through the Guard.
            if os.environ.get("LINTEL_TEST_HUMAN_EDIT"):
                page.locator("form input[type=text]:visible").first.fill(os.environ["LINTEL_TEST_HUMAN_EDIT"])
            page.locator("form button[type=submit], form input[type=submit]").first.click(no_wait_after=True)
        # Wait for the person's click (assisted fill) or for our own click's outcome.
        while self.fence is None:
            self._check_cancel()
            if self.heartbeat and self.heartbeat.app_state not in (None, "approved", "submitting"):
                raise RunEnded("cancelled")
            if self.adopt_requested.is_set():
                self.adopt_requested.clear()
                self._adopt_edits()
                raise RunEnded("completed")
            if self.restore_requested.is_set():
                self.restore_requested.clear()
                st = graph.invoke({"phase": "observe", "attempts": {}, "no_progress": 0}, {"recursion_limit": 400})
                self.browser.show_banner(page, "armed", self.a.support_mode.value)
                self.steps.add("restore", detail=f"approved values put back ({st.get('phase')})")
            self._pump(400)
        _crash("after_click")
        self.journal.write(event="clicked", application_id=self.a.application_id, fence=self.fence)
        outcome = adapters.observe(page, timeout_s=float(os.environ.get("LINTEL_OUTCOME_TIMEOUT", "30")))
        _crash("before_outcome")
        if outcome.status == "confirmed":
            for attempt in range(4):
                try:
                    res = self.api.post(f"/runner/applications/{self.a.application_id}/outcome",
                                        json={"fence": self.fence, "confirmation_text": outcome.text,
                                              "reference_number": outcome.reference, "page_hash": outcome.page_hash})
                    self.journal.write(event="outcome", application_id=self.a.application_id, fence=self.fence,
                                       result=res.get("result"), reference=outcome.reference)
                    break
                except ApiError as e:
                    if e.code == "stale_fence":
                        self.steps.add("outcome", verification="blocked", detail="stale fencing token refused")
                        raise RunEnded("stale fencing token") from e
                    time.sleep(1 + attempt)
            self.steps.add("outcome", detail=f"confirmed{' ' + outcome.reference if outcome.reference else ''}")
            self.browser.show_banner(page, "done", outcome.reference or "")
            self._complete("confirmation observed")
            return
        self.steps.add("outcome", verification="error",
                       detail="the site showed errors after the click" if outcome.status == "errors" else "no confirmation")
        self.browser.show_banner(page, "uncertain")
        # Uncertain by default: the run fails and the cloud marks the application uncertain. Never retried.
        raise RunEnded("no confirmation observed after the click")

    def _adopt_edits(self) -> None:
        diffs = getattr(self, "last_diffs", [])
        pr = read_page(self.page)
        live = {d["field_key"]: pr.live[d["field_key"]].value for d in diffs if d["field_key"] in pr.live}
        self.api.post(f"/runner/applications/{self.a.application_id}/guard-mismatch",
                      json={"diffs": [{"field_key": d["field_key"], "label": d["label"]} for d in diffs],
                            "live_values": live, "adopt": True})
        self.steps.add("adopt", detail=f"{len(live)} edit(s) sent to Lintel for re-approval")
        self.browser.show_banner(self.page, "info", "Edits sent to Lintel", "Review and approve the new payload in Lintel. "
                                 "Free-text edits go through the claim check again.")
