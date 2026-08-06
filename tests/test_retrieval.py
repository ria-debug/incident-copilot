from __future__ import annotations

from pathlib import Path

import pytest

from incidentcopilot.ablation import best, marginals, sweep
from incidentcopilot.chunking import Chunk, chunk_document, split_sentences
from incidentcopilot.corpus import build_chunks, load_corpus
from incidentcopilot.evaluate import (
    evaluate_retrieval,
    load_queries,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from incidentcopilot.retrieval import BM25, RETRIEVERS, ExpandedBM25, Hit, build_retriever, tokenize

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
QUERIES = ROOT / "evaluation" / "queries.jsonl"


@pytest.fixture(scope="module")
def docs():
    return load_corpus(CORPUS)


@pytest.fixture(scope="module")
def chunks(docs):
    return build_chunks(docs, strategy="sentence", size=180)


@pytest.fixture(scope="module")
def queries():
    return load_queries(QUERIES)


# ── chunking ───────────────────────────────────────────────────────────────────

def test_fixed_chunking_respects_size_and_overlaps():
    text = " ".join(f"w{i}" for i in range(100))
    out = chunk_document("d", text, strategy="fixed", size=30, overlap=10)
    assert all(c.n_words <= 30 for c in out)
    # Consecutive chunks must share words, or a fact spanning a boundary is lost
    # to every chunk that contains part of it.
    assert set(out[0].text.split()) & set(out[1].text.split())


def test_overlap_at_or_above_size_is_rejected():
    """Otherwise the window never advances and chunking hangs."""
    with pytest.raises(ValueError, match="overlap"):
        chunk_document("d", "a b c", strategy="fixed", size=10, overlap=10)


def test_sentence_chunking_never_splits_mid_sentence():
    text = "First sentence here. Second sentence here. Third sentence here."
    out = chunk_document("d", text, strategy="sentence", size=5)
    for c in out:
        assert not c.text.strip().endswith(("First", "Second", "Third"))


def test_oversized_single_sentence_is_emitted_whole():
    """Truncating would lose exactly the long procedural line runbooks are made of."""
    long_sentence = " ".join(f"w{i}" for i in range(200)) + "."
    out = chunk_document("d", long_sentence, strategy="sentence", size=20)
    assert len(out) == 1
    assert out[0].n_words >= 200


def test_section_chunks_carry_their_heading():
    """A procedure body rarely repeats its own topic, so a chunk stripped of its
    heading is unretrievable by the words someone would search for."""
    text = "# Doc\n\n## Connection pool exhaustion\n\nRestart the pool, then verify.\n"
    out = chunk_document("d", text, strategy="section", size=100)
    body = next(c for c in out if "Restart the pool" in c.text)
    assert "Connection pool exhaustion" in body.text
    assert body.section == "Connection pool exhaustion"


def test_split_sentences_handles_empty_and_unpunctuated():
    assert split_sentences("") == []
    assert split_sentences("no terminal punctuation") == ["no terminal punctuation"]


def test_chunk_ids_are_unique_across_the_corpus(chunks):
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_citation_is_resolvable_to_a_document(chunks, docs):
    doc_ids = {d.doc_id for d in docs}
    for c in chunks:
        assert c.citation().split("#")[0] in doc_ids


# ── tokenisation ───────────────────────────────────────────────────────────────

def test_stoplist_keeps_operationally_meaningful_short_words():
    """A general-purpose stoplist strips 'down', 'up', 'out', 'no' — every one of
    which carries meaning in an alert ('pod is down', 'no healthy upstream')."""
    toks = tokenize("the pod is down and no healthy upstream is up")
    for word in ("down", "no", "healthy", "upstream", "up"):
        assert word in toks
    assert "the" not in toks and "is" not in toks


def test_tokenizer_keeps_metric_names_intact():
    assert "pool_active_connections" in tokenize("check pool_active_connections now")


# ── retrieval ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", RETRIEVERS)
def test_every_retriever_returns_ranked_results(name, chunks):
    hits = build_retriever(name, chunks).search("connection pool saturation", k=5)
    assert hits
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_retriever_finds_the_obvious_document(chunks):
    hits = BM25(chunks).search("connection pool exhaustion leaked connection", k=3)
    assert "connection-pool-exhaustion" in {h.chunk.doc_id for h in hits}


def test_query_with_no_corpus_terms_returns_nothing(chunks):
    """Returning nothing is correct. The abstention path depends on it — an
    empty result set must not be padded with irrelevant chunks."""
    assert BM25(chunks).search("zzzqqq xyzzy plugh", k=5) == []


def test_expansion_reaches_a_document_sharing_no_query_terms(chunks):
    """The one thing expansion is for: 'stuck' never appears in the corpus."""
    plain = {h.chunk.doc_id for h in BM25(chunks).search("consumer is stuck", k=5)}
    expanded = {h.chunk.doc_id for h in ExpandedBM25(chunks).search("consumer is stuck", k=5)}
    assert len(expanded) >= len(plain)


def test_idf_is_never_negative(chunks):
    """A negative IDF would actively push a matching chunk down the ranking."""
    assert all(v > 0 for v in BM25(chunks).idf.values())


def test_empty_corpus_does_not_divide_by_zero():
    assert BM25([]).search("anything", k=3) == []


# ── metrics ────────────────────────────────────────────────────────────────────

def _hits(*doc_ids):
    return [
        Hit(chunk=Chunk(chunk_id=f"c{i}", doc_id=d, text="t"), score=1.0 - i * 0.1, rank=i + 1)
        for i, d in enumerate(doc_ids)
    ]


def test_recall_counts_documents_not_chunks():
    """Three chunks from one document is one document recalled, not three."""
    assert recall_at_k(_hits("a", "a", "a"), {"a", "b"}, 3) == 0.5


def test_precision_and_recall_are_reported_together():
    hits = _hits("a", "x", "y")
    assert recall_at_k(hits, {"a"}, 3) == 1.0
    assert precision_at_k(hits, {"a"}, 3) == pytest.approx(1 / 3)


def test_reciprocal_rank_rewards_position():
    assert reciprocal_rank(_hits("a", "b"), {"a"}) == 1.0
    assert reciprocal_rank(_hits("x", "a"), {"a"}) == 0.5
    assert reciprocal_rank(_hits("x", "y"), {"a"}) == 0.0


def test_ndcg_prefers_relevant_results_earlier():
    early = ndcg_at_k(_hits("a", "x", "y"), {"a"}, 3)
    late = ndcg_at_k(_hits("x", "y", "a"), {"a"}, 3)
    assert early == 1.0
    assert late < early


def test_unanswerable_queries_are_excluded_from_retrieval_metrics(chunks, queries):
    """They have no relevant document, so including them would drag every metric
    down by a constant and hide real differences between configurations."""
    report = evaluate_retrieval(BM25(chunks), queries, k=5)
    assert report.n_queries == sum(1 for q in queries if not q.unanswerable)
    assert report.n_queries < len(queries)


def test_zero_recall_queries_are_tracked_not_just_averaged(chunks, queries):
    report = evaluate_retrieval(BM25(chunks), queries, k=5)
    assert report.n_zero_recall == len(report.zero_recall_ids)


# ── query set ──────────────────────────────────────────────────────────────────

def test_every_labelled_document_exists(docs, queries):
    """A typo in a relevant_docs entry would silently make a query unwinnable and
    depress every configuration equally — invisible in the results."""
    known = {d.doc_id for d in docs}
    for q in queries:
        for doc_id in q.relevant_docs:
            assert doc_id in known, f"{q.id} references unknown document {doc_id!r}"


def test_query_set_covers_abstention_and_multi_document_cases(queries):
    assert any(q.unanswerable for q in queries)
    assert any(len(q.relevant_docs) > 1 for q in queries)


def test_unanswerable_queries_have_no_relevant_docs(queries):
    assert all(not q.relevant_docs for q in queries if q.unanswerable)


# ── the documented findings ────────────────────────────────────────────────────

def test_default_config_holds_up(chunks, queries):
    """Guards the shipped default. If a corpus change degrades it below these
    floors, that is a regression worth failing on."""
    report = evaluate_retrieval(BM25(chunks), queries, k=5)
    assert report.recall_at_3 >= 0.85
    assert report.mrr >= 0.85
    assert report.n_zero_recall == 0


def test_ablation_reproduces_the_finding_that_section_chunking_lost():
    """FAILURES.md finding 1. If this ever flips, the writeup is stale."""
    docs = load_corpus(CORPUS)
    queries = load_queries(QUERIES)
    cells = sweep(docs, queries, sizes=(120, 180), retrievers=("bm25",))
    marg = marginals(cells, "recall_at_3")["strategy"]
    assert marg["section"] < marg["sentence"], marg


def test_sweep_varies_every_dimension():
    docs = load_corpus(CORPUS)
    queries = load_queries(QUERIES)
    cells = sweep(docs, queries, strategies=("fixed", "sentence"), sizes=(120, 180),
                  retrievers=("bm25", "hybrid_rrf"))
    assert len(cells) == 2 * 2 * 2
    assert len({c.key for c in cells}) == len(cells)
    assert best(cells, "recall_at_3") in cells
