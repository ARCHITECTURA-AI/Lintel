from __future__ import annotations

from lintel_schemas import ClaimScope, Fact, FactAttributes, FactKind, SourceType
from lintel_trust.claimcheck import check_sentence, split_sentences


def fact(fid, statement, scope=ClaimScope.employment, kind=FactKind.achievement, **attrs):
    return Fact(
        id=fid,
        kind=kind,
        claim_scope=scope,
        statement=statement,
        attributes=FactAttributes(**attrs),
        source_type=SourceType.resume,
    )


ROLE = fact("f_role", "Backend Engineer Intern at Kite Labs, June 2024 to December 2024", kind=FactKind.role,
            employer="Kite Labs", title="Backend Engineer Intern", start="2024-06", end="2024-12")
API = fact("f_api", "Built a FastAPI service at Kite Labs that handled about 400 daily users over 6 months.",
           employer="Kite Labs", skills=["FastAPI", "Postgres"])
PROJECT = fact("f_proj", "Personal project: a Rust CLI for parsing log files, used by 3 friends.", scope=ClaimScope.project,
               skills=["Rust"])
FAMILIAR = fact("f_k8s", "Familiar with Kubernetes from a weekend course.", scope=ClaimScope.coursework, kind=FactKind.skill,
                proficiency="familiar", skills=["Kubernetes"])
ALL = [ROLE, API, PROJECT, FAMILIAR]
CTX = ["Acme", "Senior Backend Engineer"]


def run(sentence, cited):
    return check_sentence(sentence, cited, all_facts=ALL, context_terms=CTX)


def test_grounded_sentence_passes():
    r = run("At Kite Labs I built a FastAPI service that handled about 400 daily users over 6 months.", [ROLE, API])
    assert r.passed, r.checks


def test_wrong_number_fails_token_check():
    r = run("I built a FastAPI service that handled 4,000 daily users.", [API])
    assert not r.passed
    assert r.checks[0].name == "token" and "4,000" in r.checks[0].offending


def test_uncited_tool_fails():
    r = run("I built a FastAPI service on Kubernetes.", [API])
    assert not r.passed and r.checks[0].outcome == "fail"
    assert any("Kubernetes" in o for o in r.checks[0].offending)


def test_uncited_employer_fails():
    r = run("I built a FastAPI service at Google.", [API])
    assert not r.passed and "Google" in r.checks[0].offending


def test_project_as_job_fails_scope():
    r = run("I worked at a company where I wrote a Rust CLI for parsing log files.", [PROJECT])
    assert not r.passed
    assert r.checks[1].name == "scope" and r.checks[1].outcome == "fail"


def test_familiar_never_becomes_expert():
    r = run("I am an expert in Kubernetes.", [FAMILIAR])
    assert not r.passed
    assert "expert" in r.checks[1].detail.lower()
    ok = run("I am familiar with Kubernetes from a weekend course.", [FAMILIAR])
    assert ok.passed, ok.checks


def test_leadership_needs_a_fact():
    r = run("At Kite Labs I led a team that built a FastAPI service.", [ROLE, API])
    assert not r.passed
    assert "leadership" in r.checks[1].detail.lower()


def test_target_company_is_context_not_claim():
    r = run("I would love to bring this to Acme.", [])
    assert r.passed, r.checks


def test_claim_without_facts_fails():
    r = run("I have shipped many production systems.", [])
    assert not r.passed


def test_overreach_word_fails_verifier():
    r = run("I single-handedly built a FastAPI service at Kite Labs.", [ROLE, API])
    assert not r.passed
    assert r.checks[2].verdict == "overreach"


def test_go_verb_is_not_language():
    r = run("Go ahead and contact me.", [])
    assert r.checks[0].outcome == "pass"


def test_split_sentences():
    assert split_sentences("One thing. Two things! Three?") == ["One thing.", "Two things!", "Three?"]
