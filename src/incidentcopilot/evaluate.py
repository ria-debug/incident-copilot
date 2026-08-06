"""Retrieval metrics and the labelled query set.

The point of this module is that retrieval quality is measured *before* any
model sees the results. A RAG system that answers fluently from the wrong three
chunks looks fine in a demo and is wrong in production; the only way to know
which one you have is to score the retriever on its own.

Relevance is judged at **document** level, not chunk level. Chunk-level labels
would have to be re-done every time the chunking strategy changes, which makes
the ablation impossible — the thing being varied would also be the thing being
measured against.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .retrieval import Hit


@dataclass
class Query:
    id: str
    text: str
    # Documents that genuinely answer the question. More than one is common and
    # correct — several runbooks can be relevant to one symptom.
    relevant_docs: list[str]
    # Set when the honest answer is "the corpus does not cover this". These test
    # abstention, which is the behaviour that separates a usable incident tool
    # from a confident liar.
    unanswerable: bool = False
    tags: list[str] = field(default_factory=list)
    note: str = ""


def load_queries(path: Path) -> list[Query]:
    queries: list[Query] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                queries.append(Query(**json.loads(line)))
            except Exception as e:
                raise ValueError(f"{path}:{lineno}: invalid query — {e}") from e
    if not queries:
        raise ValueError(f"{path}: no queries")
    return queries


def recall_at_k(hits: list[Hit], relevant: set[str], k: int) -> float:
    """Fraction of relevant documents retrieved in the top k.

    The headline metric: a document the retriever never surfaces is one the
    generator can never cite, and no amount of prompting recovers it.
    """
    if not relevant:
        return 0.0
    found = {h.chunk.doc_id for h in hits[:k]} & relevant
    return len(found) / len(relevant)


def precision_at_k(hits: list[Hit], relevant: set[str], k: int) -> float:
    """Reported alongside recall because they trade off. Chunking small lifts
    recall by flooding the top-k with fragments; precision is what catches it."""
    if not hits[:k]:
        return 0.0
    return sum(1 for h in hits[:k] if h.chunk.doc_id in relevant) / len(hits[:k])


def reciprocal_rank(hits: list[Hit], relevant: set[str]) -> float:
    """1/rank of the first relevant hit.

    Rank order matters here in a way recall cannot express: an on-call engineer
    reads the first result. A relevant document at position 5 has technically
    been recalled and practically been missed.
    """
    for i, h in enumerate(hits, start=1):
        if h.chunk.doc_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(hits: list[Hit], relevant: set[str], k: int) -> float:
    """Binary-gain nDCG — rewards relevant documents appearing earlier."""
    seen: set[str] = set()
    dcg = 0.0
    for i, h in enumerate(hits[:k], start=1):
        if h.chunk.doc_id in relevant and h.chunk.doc_id not in seen:
            seen.add(h.chunk.doc_id)
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


@dataclass
class RetrievalReport:
    n_queries: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    precision_at_3: float
    mrr: float
    ndcg_at_5: float
    n_zero_recall: int
    zero_recall_ids: list[str]
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d.pop("per_query")
        return d


def evaluate_retrieval(retriever, queries: list[Query], *, k: int = 5) -> RetrievalReport:
    """Score a retriever. Unanswerable queries are excluded — there is no
    relevant document to recall, so including them would drag every metric down
    by a constant and obscure real differences between configurations. They are
    tested separately, in the abstention path."""
    answerable = [q for q in queries if not q.unanswerable]
    rows: list[dict[str, Any]] = []

    for q in answerable:
        hits = retriever.search(q.text, k=max(k, 5))
        relevant = set(q.relevant_docs)
        rows.append(
            {
                "id": q.id,
                "tags": q.tags,
                "recall@1": recall_at_k(hits, relevant, 1),
                "recall@3": recall_at_k(hits, relevant, 3),
                "recall@5": recall_at_k(hits, relevant, 5),
                "precision@3": precision_at_k(hits, relevant, 3),
                "rr": reciprocal_rank(hits, relevant),
                "ndcg@5": ndcg_at_k(hits, relevant, 5),
                "top_docs": [h.chunk.doc_id for h in hits[:3]],
            }
        )

    def mean(key: str) -> float:
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    zero = [r["id"] for r in rows if r["recall@5"] == 0.0]
    return RetrievalReport(
        n_queries=len(rows),
        recall_at_1=mean("recall@1"),
        recall_at_3=mean("recall@3"),
        recall_at_5=mean("recall@5"),
        precision_at_3=mean("precision@3"),
        mrr=mean("rr"),
        ndcg_at_5=mean("ndcg@5"),
        # Tracked explicitly: an average hides total failures. Twenty queries at
        # 0.9 and four at 0.0 average to a healthy-looking number, and those four
        # are the incidents where the tool is worse than useless.
        n_zero_recall=len(zero),
        zero_recall_ids=zero,
        per_query=rows,
    )
