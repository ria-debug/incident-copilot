"""Grounded answer generation with mandatory citations and a real abstention path.

Two properties matter more than answer quality here, because this is a tool
someone reaches for during an incident:

**Every claim carries a citation.** Not because citations look rigorous, but
because at 3am the useful output is "open runbook X, section Y" — an engineer
must be able to verify the advice against the source before running a command
against production. An uncitable answer is unactionable.

**Abstention is a first-class outcome.** The corpus does not cover everything.
A tool that invents a plausible procedure for an uncovered failure is worse than
no tool: it is confidently wrong at the exact moment nobody has the time to
check. `sufficient_context: false` is a success, not a fallback.

The generator is also deliberately downstream of a *measured* retriever. Prompt
quality cannot fix chunks that were never retrieved — see `evaluate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .retrieval import Hit

SYSTEM = """\
You are an incident-response assistant. An on-call engineer is mid-incident and
will act on what you say, so being wrong is more expensive than being unhelpful.

Answer **only** from the numbered context passages provided. They are the whole
of your knowledge for this question. If they do not contain the answer, say so —
do not fall back on general knowledge about the technology involved, however
confident you are.

Rules:
- Every factual claim cites the passage it came from, as [1], [2]. A sentence
  you cannot cite is a sentence you must not write.
- Set sufficient_context to false when the passages do not actually answer the
  question. Partial coverage counts as insufficient: half a procedure executed
  during an incident is worse than none.
- Never invent a command, a threshold, a config key, or a service name that does
  not appear in the passages. If a runbook says "restart the pool" without
  giving the command, say that rather than supplying a plausible one.
- Distinguish what the passages state from what they imply. Mark inference as
  inference.
- When passages conflict, say so and cite both. Do not silently pick one.

Order the response the way it will be read under pressure: the most likely cause
first, then the specific check that would confirm or eliminate it.\
"""

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sufficient_context": {"type": "boolean"},
        "answer": {"type": "string"},
        "likely_causes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cause": {"type": "string"},
                    "confirming_check": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["cause", "confirming_check", "citations"],
                "additionalProperties": False,
            },
        },
        "citations_used": {"type": "array", "items": {"type": "integer"}},
        "missing_information": {"type": "string"},
    },
    "required": [
        "sufficient_context",
        "answer",
        "likely_causes",
        "citations_used",
        "missing_information",
    ],
    "additionalProperties": False,
}


def render_context(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] source: {h.chunk.citation()}\n{h.chunk.text}")
    return "\n\n".join(blocks)


@dataclass
class GroundedAnswer:
    query: str
    sufficient_context: bool
    answer: str
    likely_causes: list[dict[str, Any]]
    citations_used: list[int]
    missing_information: str
    sources: list[str]
    # Populated by verify(); a structural check, run before anyone reads the prose.
    integrity: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def verify(answer: GroundedAnswer, hits: list[Hit]) -> dict[str, Any]:
    """Structural checks on the answer, independent of any model.

    These catch the failure modes that matter without a second API call: a
    citation pointing at a passage that was never supplied, an answer that
    claims sufficiency while citing nothing, or one that claims insufficiency
    and then answers anyway. None of these require judging the prose — they are
    contradictions visible from the structure alone, which makes them cheap
    enough to run on every single answer.
    """
    valid = set(range(1, len(hits) + 1))
    cited = set(answer.citations_used)
    for cause in answer.likely_causes:
        cited |= set(cause.get("citations", []))

    dangling = sorted(cited - valid)
    return {
        "dangling_citations": dangling,
        "has_dangling": bool(dangling),
        # An answer asserting it had enough context while citing nothing is
        # ungrounded by construction, whatever it says.
        "claims_sufficient_without_citations": answer.sufficient_context and not cited,
        # And the reverse: abstaining, then answering anyway.
        "answers_despite_insufficient": (
            not answer.sufficient_context and len(answer.answer.split()) > 60
        ),
        "n_citations": len(cited),
        "coverage": round(len(cited & valid) / len(valid), 3) if valid else 0.0,
    }


def answer_question(query: str, hits: list[Hit], client) -> GroundedAnswer:
    """`client` must expose `.complete(system=, user=, output_schema=)`."""
    if not hits:
        # No retrieval, no answer. Calling the model here would invite it to
        # answer from parametric knowledge, which is the exact failure this
        # system exists to prevent.
        return GroundedAnswer(
            query=query,
            sufficient_context=False,
            answer="No passages were retrieved for this question.",
            likely_causes=[],
            citations_used=[],
            missing_information="Retrieval returned nothing; the corpus likely does not cover this.",
            sources=[],
            integrity={"n_citations": 0, "coverage": 0.0, "has_dangling": False},
        )

    user = f"<question>\n{query}\n</question>\n\n<context>\n{render_context(hits)}\n</context>"
    call = client.complete(system=SYSTEM, user=user, output_schema=ANSWER_SCHEMA)

    if not call.ok or not isinstance(call.output, dict):
        return GroundedAnswer(
            query=query,
            sufficient_context=False,
            answer="",
            likely_causes=[],
            citations_used=[],
            missing_information="",
            sources=[h.chunk.citation() for h in hits],
            error=call.error or "non-dict output",
        )

    out = call.output
    ans = GroundedAnswer(
        query=query,
        sufficient_context=bool(out.get("sufficient_context")),
        answer=out.get("answer", ""),
        likely_causes=out.get("likely_causes", []),
        citations_used=out.get("citations_used", []),
        missing_information=out.get("missing_information", ""),
        sources=[h.chunk.citation() for h in hits],
    )
    ans.integrity = verify(ans, hits)
    return ans
