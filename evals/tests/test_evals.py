"""The claim-check eval and the database properties, as tests. The full report is `lintel-evals`."""

from __future__ import annotations

import pytest
from lintel_evals.run import claim_check


def test_no_unsupported_claim_leaks():
    r = claim_check()
    assert r["unsupported_leaked"] == 0, [e for e in r["examples"] if e["verdict"] == "leaked"]
    assert r["development"]["unsupported_leaked"] == 0
    # False blocks cost time, not credibility; they are reported, and must stay rare.
    assert r["false_blocks"] <= max(2, r["supported"] // 4)


@pytest.mark.parametrize("name", ["no_two_sends", "stale_fence_rejected", "uncertain_is_never_retried",
                                  "lifecycle_matches_the_spec", "any_change_breaks_the_approval", "no_cross_user_reads"])
def test_property(stack, name):
    from lintel_evals import properties

    getattr(properties, f"prop_{name}")()
