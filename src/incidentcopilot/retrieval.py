"""Retrievers: BM25, a term-expansion variant, and reciprocal-rank fusion.

BM25 is implemented from scratch rather than pulled in, for one reason that
matters more than dependency count: the ablation has to run for free and give
identical numbers on every machine. A hosted embedding API would make
`evaluate.py` cost money per run, which is exactly the friction that stops
people measuring retrieval at all.

The honest trade: BM25 is lexical. It cannot match "the pool ran out of
connections" to a runbook that says "connection saturation" unless a word
overlaps. `ExpandedBM25` addresses that with a hand-built domain synonym map.

The ablation says it did not work. Expansion left recall@3 unchanged and made
recall@5 *worse* (0.980 -> 0.960), buying a rounding error on MRR and a small
gain on precision@3. `RRFHybrid` fared no better — it matched plain BM25 on
every metric but one, because fusing BM25 with BM25-plus-synonyms fuses two
retrievers that fail the same way. Both are kept so the sweep can keep
demonstrating that, and the shipped default is plain BM25. See FINDINGS.md.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .chunking import Chunk

_TOKEN = re.compile(r"[a-z0-9_]+")

# Deliberately short. Operational text is dense with terms a general-purpose
# stoplist would strip — "up", "down", "out", "no", "not" all carry meaning in
# an alert ("pod is down", "no healthy upstream").
STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "for", "and", "or", "as", "it", "its",
    "this", "that", "with",
})

# Domain synonyms for query expansion. Hand-built, not learned — with a corpus
# this size a learned expansion would fit noise. Each entry is a phrasing an
# engineer types under pressure mapped to the vocabulary the docs actually use.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "slow": ("latency", "p99", "degraded"),
    "hang": ("timeout", "deadlock", "blocked"),
    "hanging": ("timeout", "deadlock", "blocked"),
    "stuck": ("deadlock", "blocked", "timeout"),
    "crash": ("oom", "restart", "panic", "exit"),
    "crashing": ("oom", "restart", "panic"),
    "down": ("outage", "unavailable", "unhealthy"),
    "error": ("5xx", "500", "exception", "failure"),
    "errors": ("5xx", "500", "exception", "failure"),
    "memory": ("oom", "heap", "rss"),
    "cpu": ("throttle", "saturation", "load"),
    "disk": ("volume", "filesystem", "inode"),
    "full": ("exhausted", "saturated", "capacity"),
    "connections": ("pool", "connection", "saturation"),
    "cert": ("certificate", "tls", "ssl", "expiry"),
    "certificate": ("tls", "ssl", "expiry", "handshake"),
    "auth": ("authentication", "token", "401", "credential"),
    "login": ("authentication", "auth", "session"),
    "queue": ("backlog", "lag", "consumer"),
    "lag": ("backlog", "queue", "consumer"),
    "rollback": ("revert", "deploy", "release"),
    "deploy": ("release", "rollout", "deployment"),
    "spike": ("surge", "burst", "increase"),
    "leak": ("leak", "growth", "unbounded", "heap"),
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Hit:
    chunk: Chunk
    score: float
    rank: int


class BM25:
    """Okapi BM25.

    `k1` controls term-frequency saturation, `b` length normalisation. The
    defaults are the standard 1.5 / 0.75 rather than tuned values — tuning them
    on 24 labelled queries would fit the eval set, not the task, and the
    resulting number would be a lie about generalisation.
    """

    def __init__(self, chunks: list[Chunk], *, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(c.text) for c in chunks]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.tf: list[Counter] = [Counter(t) for t in self.doc_tokens]

        df: Counter = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(chunks)
        # +0.5 smoothing keeps the IDF of a term present in every document at a
        # small positive value rather than negative, which would actively push
        # a matching chunk down the ranking.
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }
        self.postings: dict[str, list[int]] = defaultdict(list)
        for i, toks in enumerate(self.doc_tokens):
            for term in set(toks):
                self.postings[term].append(i)

    def _query_terms(self, query: str) -> list[str]:
        return tokenize(query)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        terms = self._query_terms(query)
        scores: dict[int, float] = defaultdict(float)
        for term in terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            # Only documents containing the term can score — the postings list
            # keeps this proportional to matches, not to corpus size.
            for i in self.postings[term]:
                freq = self.tf[i][term]
                denom = freq + self.k1 * (
                    1 - self.b + self.b * (self.doc_len[i] / (self.avg_len or 1))
                )
                scores[i] += idf * (freq * (self.k1 + 1)) / (denom or 1)

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [Hit(chunk=self.chunks[i], score=s, rank=r + 1) for r, (i, s) in enumerate(ranked)]


class ExpandedBM25(BM25):
    """BM25 over a query expanded with domain synonyms.

    Expansion terms are down-weighted rather than treated as equals: an expanded
    term is a guess about intent, and scoring it like a term the user actually
    typed lets one bad synonym outrank an exact match.
    """

    def __init__(self, chunks: list[Chunk], *, expansion_weight: float = 0.45, **kw):
        super().__init__(chunks, **kw)
        self.expansion_weight = expansion_weight

    def search(self, query: str, k: int = 5) -> list[Hit]:
        original = tokenize(query)
        expansions: list[str] = []
        for term in original:
            expansions.extend(t for t in SYNONYMS.get(term, ()) if t not in original)

        scores: dict[int, float] = defaultdict(float)
        for terms, weight in ((original, 1.0), (expansions, self.expansion_weight)):
            for term in terms:
                idf = self.idf.get(term)
                if idf is None:
                    continue
                for i in self.postings[term]:
                    freq = self.tf[i][term]
                    denom = freq + self.k1 * (
                        1 - self.b + self.b * (self.doc_len[i] / (self.avg_len or 1))
                    )
                    scores[i] += weight * idf * (freq * (self.k1 + 1)) / (denom or 1)

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [Hit(chunk=self.chunks[i], score=s, rank=r + 1) for r, (i, s) in enumerate(ranked)]


class RRFHybrid:
    """Reciprocal-rank fusion over several retrievers.

    RRF fuses on *rank*, not score, which is the reason to use it here: BM25 and
    expanded-BM25 produce scores on incompatible scales, and normalising them to
    compare would invent a relationship that does not exist.
    """

    def __init__(self, retrievers: list[BM25], *, k_rrf: int = 60):
        self.retrievers = retrievers
        self.k_rrf = k_rrf

    def search(self, query: str, k: int = 5) -> list[Hit]:
        fused: dict[str, float] = defaultdict(float)
        seen: dict[str, Chunk] = {}
        for r in self.retrievers:
            # Fetch deeper than k: a chunk ranked 8th by both retrievers should
            # be able to surface, which is the entire point of fusion.
            for hit in r.search(query, k=k * 3):
                fused[hit.chunk.chunk_id] += 1.0 / (self.k_rrf + hit.rank)
                seen[hit.chunk.chunk_id] = hit.chunk
        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [Hit(chunk=seen[cid], score=s, rank=i + 1) for i, (cid, s) in enumerate(ranked)]


def build_retriever(name: str, chunks: list[Chunk]):
    if name == "bm25":
        return BM25(chunks)
    if name == "bm25_expanded":
        return ExpandedBM25(chunks)
    if name == "hybrid_rrf":
        return RRFHybrid([BM25(chunks), ExpandedBM25(chunks)])
    raise ValueError(f"unknown retriever {name!r}")


RETRIEVERS = ("bm25", "bm25_expanded", "hybrid_rrf")
