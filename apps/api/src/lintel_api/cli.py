"""lintel-api: migrate, seed, serve, worker and admin commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def _owner_engine():
    from .config import get_settings

    return create_engine(get_settings().database_url)


def migrate(_args) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(cfg, "head")
    seed(_args)


def seed(_args) -> None:
    from sqlalchemy.orm import Session

    from .services import registry

    with Session(_owner_engine()) as db, db.begin():
        n = registry.seed(db)
    print(f"registry: {n} destination(s) added")


def make_admin(args) -> None:
    with _owner_engine().begin() as conn:
        r = conn.execute(text("UPDATE users SET is_admin = true WHERE email = :e"), {"e": args.email})
    print("ok" if r.rowcount else "no such user")


def serve(args) -> None:
    import uvicorn

    uvicorn.run("lintel_api.app:app", host=args.host, port=args.port, reload=args.reload)


def worker(_args) -> None:
    import logging

    from .worker import run_forever

    logging.basicConfig(level=logging.INFO)
    run_forever()


def public_key(_args) -> None:
    from .security import signing_public_pem

    sys.stdout.write(signing_public_pem())


def demo(args) -> None:
    from .demo import seed_demo

    seed_demo(email=args.email, password=args.password)


def main() -> None:
    p = argparse.ArgumentParser(prog="lintel-api")
    sub = p.add_subparsers(required=True)
    sub.add_parser("migrate", help="apply migrations and seed the registry").set_defaults(fn=migrate)
    sub.add_parser("seed", help="seed the destination registry").set_defaults(fn=seed)
    a = sub.add_parser("make-admin", help="let a user edit the registry")
    a.add_argument("email")
    a.set_defaults(fn=make_admin)
    s = sub.add_parser("serve", help="run the API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=serve)
    sub.add_parser("worker", help="run the queue worker and scheduler").set_defaults(fn=worker)
    sub.add_parser("public-key", help="print the approval verification key").set_defaults(fn=public_key)
    d = sub.add_parser("demo", help="create a demo account wired to Lintel Lab")
    d.add_argument("--email", default="demo@lintel.dev")
    d.add_argument("--password", default="lintel-demo-2026")
    d.set_defaults(fn=demo)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
