"""Property tests: changing any single field of a payload changes its hash."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lintel_schemas import CanonicalPayload
from lintel_trust import (
    SignatureError,
    canonical_json,
    generate_private_key_pem,
    load_private_key,
    load_public_key,
    payload_hash,
    public_key_pem,
    sign_approval,
    values_equal,
    verify_approval,
)

text = st.text(min_size=0, max_size=40)
keys = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_0123456789", min_size=1, max_size=12)


@st.composite
def payloads(draw):
    n = draw(st.integers(min_value=1, max_value=6))
    field_keys = draw(st.lists(keys, min_size=n, max_size=n, unique=True))
    answers = [
        {
            "field_key": k,
            "value": draw(st.one_of(text, st.booleans(), st.lists(text, max_size=3))),
            "fact_ids": draw(st.lists(keys, max_size=3, unique=True)),
        }
        for k in field_keys
    ]
    return {
        "application_id": draw(keys),
        "destination": {"platform": "greenhouse", "job_identity": "gh:" + draw(keys), "host": "job-boards.greenhouse.io"},
        "profile_version_id": draw(keys),
        "answers": answers,
        "documents": [{"role": "resume", "sha256": draw(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)), "field_key": None}],
        "consents": [{"field_key": "privacy_notice", "value": draw(st.booleans())}],
        "action": "submit",
    }


def _mutations(p: dict) -> list[dict]:
    out = []
    for i, a in enumerate(p["answers"]):
        m = copy.deepcopy(p)
        v = a["value"]
        if isinstance(v, bool):
            m["answers"][i]["value"] = not v
        elif isinstance(v, list):
            m["answers"][i]["value"] = [*v, "extra"]
        else:
            m["answers"][i]["value"] = v + "x"
        out.append(m)
        m2 = copy.deepcopy(p)
        m2["answers"][i]["fact_ids"] = [*a["fact_ids"], "f_new_unique"]
        out.append(m2)
    m = copy.deepcopy(p)
    m["consents"][0]["value"] = not p["consents"][0]["value"]
    out.append(m)
    m = copy.deepcopy(p)
    m["documents"][0]["sha256"] = ("0" if p["documents"][0]["sha256"][0] != "0" else "1") + p["documents"][0]["sha256"][1:]
    out.append(m)
    m = copy.deepcopy(p)
    m["destination"]["job_identity"] += "9"
    out.append(m)
    m = copy.deepcopy(p)
    m["profile_version_id"] += "9"
    out.append(m)
    return out


@settings(max_examples=200, deadline=None)
@given(payloads())
def test_any_single_field_change_changes_hash(p):
    base = payload_hash(p)
    for m in _mutations(p):
        assert payload_hash(m) != base


@settings(max_examples=100, deadline=None)
@given(payloads(), st.randoms())
def test_order_of_unordered_lists_does_not_change_hash(p, rnd):
    shuffled = copy.deepcopy(p)
    rnd.shuffle(shuffled["answers"])
    for a in shuffled["answers"]:
        rnd.shuffle(a["fact_ids"])
    assert payload_hash(shuffled) == payload_hash(p)


def test_canonical_json_is_sorted_utf8():
    p = {"b": "é", "a": 1}
    assert canonical_json(p) == '{"a":1,"b":"é"}'.encode()


def test_pydantic_and_dict_hash_equal():
    d = {
        "application_id": "app_91",
        "destination": {"platform": "greenhouse", "job_identity": "gh:acme:4412", "host": "job-boards.greenhouse.io"},
        "profile_version_id": "pv_14",
        "answers": [{"field_key": "q_backend", "value": "...", "fact_ids": ["f_12", "f_18"]}],
        "documents": [{"role": "resume", "sha256": "ab" * 32, "field_key": None}],
        "consents": [{"field_key": "privacy_notice", "value": True}],
        "action": "submit",
    }
    assert payload_hash(CanonicalPayload.model_validate(d)) == payload_hash(d)


def test_signed_approval_roundtrip_and_tamper():
    key = load_private_key(generate_private_key_pem())
    pub = load_public_key(public_key_pem(key))
    exp = datetime.now(UTC) + timedelta(minutes=30)
    a = sign_approval(key, approval_id="ap1", application_id="app1", payload_hash="h" * 64, runner_device_id="dev1", expires_at=exp)
    verify_approval(pub, a, payload_hash="h" * 64, runner_device_id="dev1")
    with pytest.raises(SignatureError):
        verify_approval(pub, a, payload_hash="x" * 64, runner_device_id="dev1")
    with pytest.raises(SignatureError):
        verify_approval(pub, a, payload_hash="h" * 64, runner_device_id="dev2")
    forged = a.model_copy(update={"expires_at": exp + timedelta(days=1)})
    with pytest.raises(SignatureError):
        verify_approval(pub, forged, payload_hash="h" * 64, runner_device_id="dev1")
    with pytest.raises(SignatureError):
        verify_approval(pub, a, payload_hash="h" * 64, runner_device_id="dev1", now=exp + timedelta(seconds=1))
    other = load_public_key(public_key_pem(load_private_key(generate_private_key_pem())))
    with pytest.raises(SignatureError):
        verify_approval(other, a, payload_hash="h" * 64, runner_device_id="dev1")


def test_normalization_ignores_whitespace_not_wording():
    assert values_equal("textarea", "Hello  world\r\n", "Hello world")
    assert not values_equal("textarea", "Hello world", "Hello, world")
    assert values_equal("checkbox", True, "on")
    assert not values_equal("checkbox", True, False)
    assert values_equal("email", "A@B.com ", "a@b.com")
    assert values_equal("multiselect", ["b", "a"], ["a", "b"])
