"""Dense retrieval: the embedding store, the retriever, and the claim it makes.

Two tiers, deliberately. The unit tests build a store from hand-written vectors
so the machinery (cosine ranking, cache misses, round-tripping) is tested
without a model and without a network. The integration tests run against the
*committed* vectors and the real corpus, because the interesting question is not
whether a dot product works but whether dense retrieval reaches a document BM25
cannot -- and that is a claim about this corpus, not about the code.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from incidentcopilot.ablation import chunk_configs
from incidentcopilot.chunking import Chunk
from incidentcopilot.cli import DEFAULT_RETRIEVER, DEFAULT_SIZE, DEFAULT_STRATEGY
from incidentcopilot.corpus import build_chunks, load_corpus
from incidentcopilot.embeddings import (
    DEFAULT_CACHE,
    MODEL,
    EmbeddingStore,
    MissingEmbeddings,
    text_key,
)
from incidentcopilot.evaluate import evaluate_retrieval, load_queries
from incidentcopilot.retrieval import BM25, DenseRetriever, build_retriever

ROOT = Path(__file__).resolve().parents[1]


def _store(mapping: dict[str, list[float]]) -> EmbeddingStore:
    texts = list(mapping)
    vectors = np.array([mapping[t] for t in texts], dtype=np.float32)
    return EmbeddingStore.from_vectors(texts, vectors, model="test-model")


# ── the store ──────────────────────────────────────────────────────────────────

def test_vectors_are_stored_unit_length_so_a_dot_product_is_cosine():
    """Normalising once at build time keeps the retriever a single matmul, and
    keeps score comparable across chunks of wildly different length."""
    store = _store({"a": [3.0, 4.0], "b": [0.0, 2.0]})
    norms = np.linalg.norm(store.encode(["a", "b"]), axis=1)
    assert np.allclose(norms, 1.0)


def test_a_text_with_no_committed_vector_raises_rather_than_scoring_zero():
    """A silent zero vector would rank every chunk equally and look like a weak
    result instead of a missing one -- exactly the failure this repo exists to
    stop shipping."""
    store = _store({"a": [1.0, 0.0]})
    with pytest.raises(MissingEmbeddings, match="regenerate"):
        store.encode(["a", "never embedded"])


def test_the_error_names_what_was_missing():
    store = _store({"a": [1.0, 0.0]})
    with pytest.raises(MissingEmbeddings) as e:
        store.encode(["never embedded"])
    assert "never embedded" in str(e.value)


def test_store_round_trips_through_disk(tmp_path):
    store = _store({"a": [1.0, 0.0], "b": [0.0, 1.0]})
    path = tmp_path / "vectors.npz"
    store.save(path)
    loaded = EmbeddingStore.load(path)
    assert loaded.model == "test-model"
    assert np.allclose(loaded.encode(["a", "b"]), store.encode(["a", "b"]))


def test_lookup_is_by_content_not_position():
    """Chunk ids change with every chunking config; the text does not. Keying on
    a hash of the text is what lets one committed cache serve all 15 configs."""
    store = _store({"same text": [1.0, 0.0]})
    assert text_key("same text") in store
    assert text_key("other text") not in store


# ── the retriever ──────────────────────────────────────────────────────────────

def _chunk(cid: str, text: str, doc: str | None = None) -> Chunk:
    return Chunk(chunk_id=cid, doc_id=doc or cid, text=text)


def test_dense_ranks_by_cosine_similarity_to_the_query():
    store = _store({
        "query": [1.0, 0.0],
        "near": [0.9, 0.1],
        "orthogonal": [0.0, 1.0],
        "opposite": [-1.0, 0.0],
    })
    chunks = [_chunk("c1", "opposite"), _chunk("c2", "orthogonal"), _chunk("c3", "near")]
    hits = DenseRetriever(chunks, store).search("query", k=3)
    assert [h.chunk.chunk_id for h in hits] == ["c3", "c2", "c1"]
    assert [h.rank for h in hits] == [1, 2, 3]
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_dense_returns_results_where_bm25_abstains():
    """The behavioural difference worth knowing before trusting it: BM25 returns
    nothing when no term matches, and dense retrieval always returns its k
    nearest neighbours however far away they are. Abstention therefore cannot
    live in the retriever once dense is in the mix -- it lives in generation,
    where `sufficient_context: false` already decides it."""
    store = _store({"zzzqqq xyzzy": [1.0, 0.0], "unrelated": [0.0, 1.0]})
    chunks = [_chunk("c1", "unrelated")]
    assert BM25(chunks).search("zzzqqq xyzzy", k=5) == []
    assert len(DenseRetriever(chunks, store).search("zzzqqq xyzzy", k=5)) == 1


def test_dense_respects_k():
    store = _store({"q": [1.0, 0.0], "a": [1.0, 0.0], "b": [0.9, 0.1], "c": [0.8, 0.2]})
    chunks = [_chunk("c1", "a"), _chunk("c2", "b"), _chunk("c3", "c")]
    assert len(DenseRetriever(chunks, store).search("q", k=2)) == 2


def test_dense_on_an_empty_corpus_returns_nothing():
    assert DenseRetriever([], _store({"q": [1.0, 0.0]})).search("q", k=3) == []


def test_dense_surfaces_a_missing_query_vector_rather_than_ranking_at_random():
    store = _store({"a": [1.0, 0.0]})
    with pytest.raises(MissingEmbeddings):
        DenseRetriever([_chunk("c1", "a")], store).search("never embedded", k=3)


# ── against the committed vectors ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def store():
    return EmbeddingStore.load(DEFAULT_CACHE)


@pytest.fixture(scope="module")
def corpus_docs():
    return load_corpus(ROOT / "corpus")


@pytest.fixture(scope="module")
def labelled_queries():
    return load_queries(ROOT / "evaluation" / "queries.jsonl")


def test_committed_vectors_cover_every_text_the_sweep_will_ask_for(
    store, corpus_docs, labelled_queries
):
    """The gate that stops a corpus edit silently invalidating the dense rows.
    Without it, editing one runbook would make `ablate` raise mid-sweep in CI
    with no indication that regeneration is the fix."""
    texts: list[str] = []
    for strategy, size, overlap in chunk_configs():
        texts += [
            c.text for c in build_chunks(corpus_docs, strategy=strategy, size=size, overlap=overlap)
        ]
    texts += [q.text for q in labelled_queries]
    assert store.covers(texts) == []


def test_committed_vectors_come_from_the_declared_model(store):
    assert store.model == MODEL


def test_dense_promotes_a_relevant_document_bm25_ranks_below_first(
    store, corpus_docs, labelled_queries
):
    """Where the vocabulary gap actually shows up: rank 1, not recall@5.

    The going-in expectation was that dense would recover documents BM25 misses
    entirely. It does not — BM25 reaches recall@5 0.980 on this corpus, so there
    is almost nothing left to recover that deep. What dense changes is the
    ordering at the top, which is the position an on-call engineer actually
    reads. Asserted at k=1 because that is where the effect is real; the k=5
    version of this test was written first and failed, and FINDINGS.md finding 6
    reports that rather than the test being softened until it passed.
    """
    chunks = build_chunks(corpus_docs, strategy="sentence", size=180, overlap=39)
    bm25, dense = BM25(chunks), DenseRetriever(chunks, store)
    promoted = {
        q.id
        for q in labelled_queries
        if not q.unanswerable
        and (set(q.relevant_docs) & {h.chunk.doc_id for h in dense.search(q.text, k=1)})
        - {h.chunk.doc_id for h in bm25.search(q.text, k=1)}
    }
    assert promoted, "dense ranked nothing relevant first that BM25 did not"


def test_dense_alone_loses_to_bm25_on_deep_recall(store, corpus_docs, labelled_queries):
    """FINDINGS.md finding 6, first half. Dense retrieval is not a free upgrade:
    on its own it trades recall@5 and introduces a zero-recall query, which is
    the outcome this repo tracks separately precisely because averages hide it.
    If this ever flips, the writeup is stale."""
    chunks = build_chunks(corpus_docs, strategy="sentence", size=180, overlap=39)
    bm25 = evaluate_retrieval(BM25(chunks), labelled_queries, k=5)
    dense = evaluate_retrieval(DenseRetriever(chunks, store), labelled_queries, k=5)
    assert dense.recall_at_5 < bm25.recall_at_5
    assert dense.mrr > bm25.mrr


def test_fusing_dense_with_bm25_beats_either_alone(store, corpus_docs, labelled_queries):
    """FINDINGS.md finding 6, second half — and the test of the prediction
    finding 4 made.

    Fusing BM25 with BM25-plus-synonyms bought nothing because both fail the
    same way. The stated prediction was that fusion would pay once the two
    retrievers fail differently. Lexical exactness and vocabulary-free
    similarity is that pair, and this is the assertion that holds the prediction
    to account.
    """
    chunks = build_chunks(corpus_docs, strategy="sentence", size=180, overlap=39)
    scores = {
        name: evaluate_retrieval(
            build_retriever(name, chunks, store=store), labelled_queries, k=5
        )
        for name in ("bm25", "dense", "hybrid_dense")
    }
    fused = scores["hybrid_dense"]
    assert fused.mrr > scores["bm25"].mrr
    assert fused.mrr > scores["dense"].mrr
    assert fused.recall_at_3 > scores["bm25"].recall_at_3
    # Fusion also repairs the zero-recall query dense alone introduced.
    assert fused.n_zero_recall == 0


def test_hybrid_dense_fuses_both_retrievers_rather_than_echoing_one(store, corpus_docs):
    chunks = build_chunks(corpus_docs, strategy="sentence", size=180, overlap=39)
    query = "a bunch of different pods restarted on the same node"
    fused = {h.chunk.chunk_id for h in build_retriever("hybrid_dense", chunks, store=store).search(query, k=5)}
    assert fused & {h.chunk.chunk_id for h in BM25(chunks).search(query, k=5)}
    assert fused & {h.chunk.chunk_id for h in DenseRetriever(chunks, store).search(query, k=5)}


def test_the_shipped_default_is_the_configuration_the_ablation_chose(
    store, corpus_docs, labelled_queries
):
    """The repo's rule is that the sweep picks the default, not taste. This
    pins the CLI defaults to the winning cell and holds it to floors only that
    cell clears -- if a corpus change degrades it below them, that is a
    regression worth failing on rather than quietly shipping."""
    chunks = build_chunks(
        corpus_docs, strategy=DEFAULT_STRATEGY, size=DEFAULT_SIZE, overlap=39
    )
    report = evaluate_retrieval(
        build_retriever(DEFAULT_RETRIEVER, chunks, store=store), labelled_queries, k=5
    )
    assert report.mrr >= 0.95
    assert report.recall_at_1 >= 0.70
    assert report.recall_at_3 >= 0.90
    assert report.n_zero_recall == 0
