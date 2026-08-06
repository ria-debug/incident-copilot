"""The grounding contract: citations, abstention, and structural integrity."""

from __future__ import annotations

from incidentcopilot.answer import (
    ANSWER_SCHEMA,
    SYSTEM,
    GroundedAnswer,
    answer_question,
    render_context,
    verify,
)
from incidentcopilot.chunking import Chunk
from incidentcopilot.client import Call
from incidentcopilot.retrieval import Hit


def _hits(n=3):
    return [
        Hit(
            chunk=Chunk(chunk_id=f"c{i}", doc_id=f"doc-{i}", text=f"passage {i}", section=f"S{i}"),
            score=1.0,
            rank=i + 1,
        )
        for i in range(n)
    ]


class FakeClient:
    def __init__(self, output):
        self.output = output
        self.last_user = ""

    def complete(self, *, system, user, output_schema=None):
        self.last_user = user
        if isinstance(self.output, Exception):
            return Call(output={}, error=str(self.output))
        return Call(output=self.output)


def _good_output(**kw):
    base = {
        "sufficient_context": True,
        "answer": "The pool is saturated [1].",
        "likely_causes": [
            {"cause": "leaked connection", "confirming_check": "check sawtooth", "citations": [1]}
        ],
        "citations_used": [1, 2],
        "missing_information": "",
    }
    base.update(kw)
    return base


# ── context rendering ──────────────────────────────────────────────────────────

def test_context_is_numbered_and_carries_a_resolvable_source():
    """The citation must name a place an engineer can open, not just a number."""
    text = render_context(_hits(2))
    assert "[1] source: doc-0#S0" in text
    assert "[2] source: doc-1#S1" in text


def test_prompt_forbids_answering_from_general_knowledge():
    assert "only" in SYSTEM.lower()
    assert "do not fall back on general knowledge" in SYSTEM.lower()
    assert "sufficient_context" in SYSTEM


def test_schema_requires_abstention_and_citation_fields():
    required = set(ANSWER_SCHEMA["required"])
    assert {"sufficient_context", "citations_used", "missing_information"} <= required
    assert ANSWER_SCHEMA["additionalProperties"] is False


# ── the no-retrieval short circuit ─────────────────────────────────────────────

def test_no_hits_abstains_without_calling_the_model():
    """Calling the model with no context invites it to answer from parametric
    knowledge — the exact failure this system exists to prevent."""
    client = FakeClient(_good_output())
    result = answer_question("anything", [], client)
    assert result.sufficient_context is False
    assert client.last_user == ""  # never called


# ── integrity checks ───────────────────────────────────────────────────────────

def test_dangling_citation_is_caught():
    """Citing [7] when only 3 passages were supplied is a fabricated source."""
    ans = GroundedAnswer(
        query="q", sufficient_context=True, answer="x", likely_causes=[],
        citations_used=[1, 7], missing_information="", sources=[],
    )
    integ = verify(ans, _hits(3))
    assert integ["has_dangling"]
    assert integ["dangling_citations"] == [7]


def test_dangling_citation_inside_a_cause_is_also_caught():
    ans = GroundedAnswer(
        query="q", sufficient_context=True, answer="x",
        likely_causes=[{"cause": "c", "confirming_check": "k", "citations": [9]}],
        citations_used=[1], missing_information="", sources=[],
    )
    assert verify(ans, _hits(3))["dangling_citations"] == [9]


def test_sufficient_without_any_citation_is_flagged():
    """Ungrounded by construction, whatever the prose says."""
    ans = GroundedAnswer(
        query="q", sufficient_context=True, answer="Confident claim.", likely_causes=[],
        citations_used=[], missing_information="", sources=[],
    )
    assert verify(ans, _hits(3))["claims_sufficient_without_citations"]


def test_abstaining_then_answering_anyway_is_flagged():
    ans = GroundedAnswer(
        query="q", sufficient_context=False, answer=" ".join(["word"] * 100),
        likely_causes=[], citations_used=[], missing_information="", sources=[],
    )
    assert verify(ans, _hits(3))["answers_despite_insufficient"]


def test_clean_answer_trips_nothing():
    ans = GroundedAnswer(
        query="q", sufficient_context=True, answer="Grounded [1].",
        likely_causes=[{"cause": "c", "confirming_check": "k", "citations": [2]}],
        citations_used=[1], missing_information="", sources=[],
    )
    integ = verify(ans, _hits(3))
    assert not integ["has_dangling"]
    assert not integ["claims_sufficient_without_citations"]
    assert not integ["answers_despite_insufficient"]
    assert integ["n_citations"] == 2
    assert integ["coverage"] == round(2 / 3, 3)


# ── end to end ─────────────────────────────────────────────────────────────────

def test_answer_runs_integrity_checks_automatically():
    result = answer_question("q", _hits(3), FakeClient(_good_output()))
    assert result.integrity
    assert result.sources == ["doc-0#S0", "doc-1#S1", "doc-2#S2"]


def test_model_abstention_is_passed_through_not_overridden():
    out = _good_output(sufficient_context=False, answer="", missing_information="No redis docs.")
    result = answer_question("redis?", _hits(2), FakeClient(out))
    assert result.sufficient_context is False
    assert result.missing_information == "No redis docs."


def test_api_error_becomes_a_failed_answer_not_an_exception():
    result = answer_question("q", _hits(2), FakeClient(RuntimeError("overloaded")))
    assert result.error == "overloaded"
    assert result.sufficient_context is False


def test_question_and_context_both_reach_the_model():
    client = FakeClient(_good_output())
    answer_question("why is the pool saturated", _hits(2), client)
    assert "why is the pool saturated" in client.last_user
    assert "passage 0" in client.last_user
