"""lintel: the Local Runner's command line.

  lintel pair --api https://your-lintel        pair this machine with a device code
  lintel start                                 open the browser and take work
  lintel prepare <job or careers URL>          add a role to Lintel from the terminal
  lintel status                                show pairing and recent runs
  lintel unpair                                forget this device locally
"""

from __future__ import annotations

import argparse
import logging
import platform
import signal
import socket
import sys
import time

from lintel_schemas import RunAssignment

from . import __version__
from . import config as cfgmod
from .browser import Browser
from .client import Api, ApiError
from .engine import RunExecutor

log = logging.getLogger("lintel.runner")


def _api(cfg: cfgmod.RunnerConfig) -> Api:
    token = cfgmod.load_token(cfg.device_id)
    if not token:
        print("This runner isn't paired. Run: lintel pair", file=sys.stderr)
        sys.exit(2)
    return Api(cfg.api_url, token)


def pair(args) -> None:
    cfg = cfgmod.load()
    if args.api:
        cfg.api_url = args.api.rstrip("/")
    api = Api(cfg.api_url)
    name = args.name or f"{socket.gethostname()} ({platform.system()})"
    start = api.post("/runner/pair/start", json={"name": name, "platform": f"{platform.system()} {platform.machine()}"})
    print()
    print("  Pair this runner with your Lintel account")
    print(f"  1. Open {start['verification_url']}")
    print(f"  2. Enter the code   {start['user_code']}")
    print()
    deadline = time.monotonic() + start["expires_in"]
    while time.monotonic() < deadline:
        time.sleep(start.get("interval", 2))
        r = api.post("/runner/pair/poll", json={"device_code": start["device_code"], "runner_version": __version__})
        if r["status"] == "approved":
            cfg.device_id = r["device_id"]
            cfg.device_name = name
            cfg.public_key_pem = r["public_key_pem"]
            where = cfgmod.store_token(r["device_id"], r["token"])
            cfgmod.save(cfg)
            print(f"  Paired as “{name}”. Token stored in {where}.")
            print("  Start the runner with: lintel start")
            return
        if r["status"] in ("expired", "unknown", "consumed"):
            print(f"  Pairing {r['status']}. Run lintel pair again.", file=sys.stderr)
            sys.exit(1)
    print("  The code expired. Run lintel pair again.", file=sys.stderr)
    sys.exit(1)


def status(_args) -> None:
    cfg = cfgmod.load()
    print(f"API:     {cfg.api_url}")
    print(f"Device:  {cfg.device_name or '(not paired)'} {cfg.device_id or ''}")
    if not cfg.device_id:
        return
    api = _api(cfg)
    try:
        conf = api.get("/runner/config")
        print(f"Account: {conf['user']['email']}")
        for r in api.get("/runner/runs")[:8]:
            print(f"  {r['created_at'][:19]}  {r['kind']:<9} {r['state']:<12} {r.get('ended_reason') or ''}")
    except ApiError as exc:
        print(f"Not reachable or revoked: {exc.message}")


def unpair(_args) -> None:
    cfg = cfgmod.load()
    cfgmod.forget(cfg.device_id)
    print("Forgot this device. Revoke it from Devices in Lintel too, if you haven't.")


def prepare(args) -> None:
    cfg = cfgmod.load()
    api = _api(cfg)
    r = api.post("/runner/prepare", json={"url": args.url})
    print(f"Added. Open {r['link']} to see the fit brief.")


def start(args) -> None:
    cfg = cfgmod.load()
    if args.headless:
        cfg.headless = True
    api = _api(cfg)
    conf = api.get("/runner/config")
    cfg.public_key_pem = conf["public_key_pem"]
    cfgmod.save(cfg)
    token = cfgmod.load_token(cfg.device_id)
    browser = Browser(cfg.profile_dir, headless=cfg.headless)
    browser.start()
    stop = {"now": False}

    def _sig(*_a):
        # Stop promptly. A run in flight is recovered by the cloud: its lease expires, and a click
        # whose outcome wasn't seen becomes "submission uncertain". Nothing is ever resent.
        stop["now"] = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    print(f"Lintel runner started for {conf['user']['email']} as “{conf['device_name']}”. Waiting for work…")
    idle = 0
    last_work = time.monotonic()
    try:
        while not stop["now"]:
            try:
                data = api.post("/runner/claim")
            except ApiError as exc:
                if exc.status == 401:
                    print("This device was revoked. Pair again with: lintel pair", file=sys.stderr)
                    return
                log.warning("claim failed: %s", exc)
                data = None
            except Exception as exc:  # noqa: BLE001 - offline: keep trying quietly
                log.warning("API unreachable: %s", exc)
                data = None
            if data:
                idle = 0
                last_work = time.monotonic()
                a = RunAssignment.model_validate(data)
                print(f"→ {a.kind.value} run for application {a.application_id[:8]}")
                RunExecutor(cfg, token, api, browser, a).execute()
                print(f"  {a.kind.value} run finished")
                if args.once:
                    return
                continue
            idle += 1
            if args.idle_exit and time.monotonic() - last_work > args.idle_exit:
                print("No work. Runner stopped.")
                return
            # pump browser events so open windows stay responsive between runs
            for p in list(browser.pages.values()):
                if not p.is_closed():
                    try:
                        p.wait_for_timeout(50)
                    except Exception:  # noqa: BLE001
                        pass
            time.sleep(min(2.0, 0.5 + idle * 0.1))
    except KeyboardInterrupt:
        print("Runner stopped.")
    finally:
        browser.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="lintel", description="Lintel Local Runner")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(required=True)
    a = sub.add_parser("pair", help="pair this machine with your account")
    a.add_argument("--api", help="Lintel API URL, e.g. http://localhost:8000")
    a.add_argument("--name", help="a name for this device")
    a.set_defaults(fn=pair)
    s = sub.add_parser("start", help="open the browser and take work")
    s.add_argument("--headless", action="store_true", help="for CI only; real use is headed")
    s.add_argument("--once", action="store_true", help="exit after one run")
    s.add_argument("--idle-exit", type=float, default=0, metavar="SECONDS",
                   help="exit when no work has arrived for this long (for scripts)")
    s.set_defaults(fn=start)
    sub.add_parser("status", help="show pairing and recent runs").set_defaults(fn=status)
    sub.add_parser("unpair", help="forget this device locally").set_defaults(fn=unpair)
    pr = sub.add_parser("prepare", help="add a job or careers URL to Lintel")
    pr.add_argument("url")
    pr.set_defaults(fn=prepare)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
