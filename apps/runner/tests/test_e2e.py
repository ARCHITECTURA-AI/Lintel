"""The shipped runner, headless, against Lintel Lab. Slower; the full suite is `lintel-evals`."""

from __future__ import annotations

import pytest
from lintel_evals import scenarios as sc

pytestmark = pytest.mark.e2e


def test_questions_on_the_live_form_are_asked_then_filled(stack):
    r = sc.lab_flow(stack, "lever", "lever", "northwind", "Software Engineer, Data Platform",
                    "2c1f9a40-5d1e-4bb0-9c2e-8a3f6e2b7d10")
    assert r["passed"], r


def test_the_guard_blocks_a_changed_field(stack):
    r = sc.guard_mismatch(stack)
    assert r["passed"], r


@pytest.mark.parametrize("point,expected", [("before_intent", "approved"), ("after_click", "submission_uncertain")])
def test_a_crash_never_sends_twice(stack, point, expected):
    r = sc.crash_test(stack, point, point, expected)
    assert r["passed"] and not r["resent"], r


def test_a_timeout_after_submit_is_uncertain_not_retried(stack):
    r = sc.lab_flow(stack, "timeout", "greenhouse", "initech", "Platform Engineer (timeout after submit)", "9004",
                    expect="submission_uncertain")
    assert r["passed"], r
