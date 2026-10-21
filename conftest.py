"""Shared fixtures: a real stack (Postgres, API, Lintel Lab) for integration and end-to-end tests.

Tests that need it are skipped, with the reason, when Postgres isn't reachable. Start it with
scripts/dev-db.sh, or point LINTEL_TEST_DATABASE_URL at another database you can drop.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator

import psycopg
import pytest


def _db_up() -> str | None:
    from lintel_evals.harness import TEST_DSN

    try:
        with psycopg.connect(TEST_DSN.replace("+psycopg", ""), connect_timeout=3):
            return None
    except psycopg.Error as exc:
        return f"test database unreachable ({exc.__class__.__name__}); run scripts/dev-db.sh"


@pytest.fixture(scope="session")
def stack() -> Iterator:
    reason = _db_up()
    if reason:
        pytest.skip(reason)
    from lintel_evals.harness import running_stack

    with running_stack() as s:
        yield s


_ids = itertools.count(1)


@pytest.fixture
def account(stack) -> Callable:
    """A demo-shaped account watching the given Lab companies."""

    def make(*companies: str):
        return stack.account(f"t{next(_ids)}@lintel.dev").create(companies=companies or ("acme",))

    return make


@pytest.fixture(scope="session")
def db_ready() -> None:
    reason = _db_up()
    if reason:
        pytest.skip(reason)
