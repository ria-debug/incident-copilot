"""Encodes every text the sweep can ask for, once, and commits the vectors.

Run after any change to the corpus, the chunking configurations, or the query
set. Nothing on the evaluation path runs the model: `ablate`, `evaluate` and the
tests all read the committed cache, which is what keeps the 75-cell sweep
offline, free and byte-reproducible in CI.

    uv run python scripts/build_embeddings.py

The chunk configurations come from `ablation.chunk_configs()` rather than being
restated here. Restating them is the bug this import exists to prevent: a size
added to the sweep and forgotten here would leave one row of the ablation
uncovered, and the failure would surface as an exception mid-sweep in CI rather
than as "regenerate the cache".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from incidentcopilot.ablation import chunk_configs
from incidentcopilot.corpus import build_chunks, load_corpus
from incidentcopilot.embeddings import DEFAULT_CACHE, MODEL, EmbeddingStore
from incidentcopilot.evaluate import load_queries


def collect_texts() -> list[str]:
    """Every chunk text across all 15 chunking configurations, plus the queries.

    De-duplicated, and the order is deterministic: different configurations
    produce overlapping chunk texts, and the cache is keyed by content anyway.
    """
    docs = load_corpus(ROOT / "corpus")
    seen: dict[str, None] = {}
    for strategy, size, overlap in chunk_configs():
        for chunk in build_chunks(docs, strategy=strategy, size=size, overlap=overlap):
            seen.setdefault(chunk.text, None)
    for query in load_queries(ROOT / "evaluation" / "queries.jsonl"):
        seen.setdefault(query.text, None)
    return sorted(seen)


def main() -> int:
    from model2vec import StaticModel

    texts = collect_texts()
    print(f"[encode] {len(texts)} unique texts with {MODEL}")
    vectors = StaticModel.from_pretrained(MODEL).encode(texts)
    store = EmbeddingStore.from_vectors(texts, vectors, model=MODEL)
    store.save(DEFAULT_CACHE)

    size_kb = DEFAULT_CACHE.stat().st_size / 1024
    print(
        f"[written] {DEFAULT_CACHE} — {len(texts)} vectors, "
        f"dim {store.matrix.shape[1]}, {size_kb:.0f} KB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
