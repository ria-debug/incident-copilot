"""CLI: `ablate`, `evaluate`, `retrieve`, `ask`.

The first three are free and offline — they exercise retrieval, which is where
the quality of a RAG system is actually decided. Only `ask` calls the API.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ablation import best, default_overlap, marginals, render_markdown, sweep, write_results
from .corpus import build_chunks, load_corpus
from .evaluate import evaluate_retrieval, load_queries
from .retrieval import RETRIEVERS, build_retriever, default_store

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "corpus"
DEFAULT_QUERIES = ROOT / "evaluation" / "queries.jsonl"

# Chosen by the ablation, not by taste — and not the configuration I expected.
# `section` chunking (my hypothesis) came last for every lexical retriever, and
# neither query expansion nor BM25-on-BM25 fusion beat plain BM25.
#
# Dense retrieval changed the answer. `hybrid_dense` is the only retriever with
# no zero-recall cell anywhere in the sweep, and it takes MRR 0.908 -> 0.973 on
# this configuration. It is NOT the top cell by recall@3 — `fixed/180` is, by
# 0.034 — but finding 5 is that ranking on recall@3 alone ships the retriever
# that reads worse first, and this cell wins R@1 by 0.080 and MRR by 0.040.
# See results/ablation.md and FINDINGS.md findings 6 and 7.
DEFAULT_STRATEGY = "sentence"
DEFAULT_SIZE = 180
DEFAULT_RETRIEVER = "hybrid_dense"


def _index(args, *, live: bool = False):
    """`live` lets the dense retriever embed a query nobody has embedded before.

    On for `retrieve` and `ask`, where the query is whatever the user typed. Off
    for `evaluate`, where every query is committed and a missing vector means the
    corpus changed and the numbers are stale — computing it silently would hide
    the one thing worth being told.
    """
    docs = load_corpus(Path(args.corpus))
    overlap = args.overlap if args.overlap is not None else default_overlap(args.size)
    chunks = build_chunks(docs, strategy=args.strategy, size=args.size, overlap=overlap)
    store = default_store(live=True) if live and "dense" in args.retriever else None
    return docs, chunks, build_retriever(args.retriever, chunks, store=store)


def _cmd_ablate(args) -> int:
    docs = load_corpus(Path(args.corpus))
    queries = load_queries(Path(args.queries))
    cells = sweep(docs, queries)
    out = Path(args.out)
    write_results(cells, out, metric=args.metric)
    print(render_markdown(cells, metric=args.metric))
    champ = best(cells, args.metric)
    print(f"\n[best] {champ.key}", file=sys.stderr)
    print(f"[marginals] {json.dumps(marginals(cells, args.metric))}", file=sys.stderr)
    print(f"[written] {out}/ablation.md, {out}/ablation.json", file=sys.stderr)
    return 0


def _cmd_evaluate(args) -> int:
    _, chunks, retriever = _index(args)
    queries = load_queries(Path(args.queries))
    report = evaluate_retrieval(retriever, queries, k=args.k)

    print(f"config: {args.strategy}/{args.size}/{args.retriever} · {len(chunks)} chunks")
    for k, v in report.to_dict().items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    if report.zero_recall_ids:
        # Printed prominently: an average hides total failures, and these are the
        # queries where the tool would be actively misleading.
        print(f"\nzero-recall queries (nothing relevant in top {args.k}):")
        for row in report.per_query:
            if row["recall@5"] == 0.0:
                print(f"  {row['id']}: retrieved {row['top_docs']}")
    return 0


def _cmd_retrieve(args) -> int:
    _, _, retriever = _index(args, live=True)
    for hit in retriever.search(args.query, k=args.k):
        print(f"[{hit.rank}] {hit.chunk.citation()}  score={hit.score:.3f}")
        print(f"    {hit.chunk.text[:220]}...\n")
    return 0


def _cmd_ask(args) -> int:
    from .answer import answer_question
    from .client import ClaudeClient

    _, _, retriever = _index(args, live=True)
    hits = retriever.search(args.query, k=args.k)
    result = answer_question(args.query, hits, ClaudeClient(model=args.model))

    if result.error:
        print(f"error: {result.error}", file=sys.stderr)
        return 1

    if not result.sufficient_context:
        print("INSUFFICIENT CONTEXT — the corpus does not answer this.\n")
        print(result.missing_information or result.answer)
        print(f"\nretrieved anyway: {', '.join(result.sources)}")
        return 0

    print(result.answer, "\n")
    if result.likely_causes:
        print("Likely causes, most probable first:\n")
        for i, c in enumerate(result.likely_causes, start=1):
            cites = ", ".join(f"[{n}]" for n in c.get("citations", []))
            print(f"{i}. {c['cause']} {cites}")
            print(f"   check: {c['confirming_check']}\n")
    print("Sources:")
    for i, src in enumerate(result.sources, start=1):
        print(f"  [{i}] {src}")

    integ = result.integrity
    if integ.get("has_dangling"):
        print(
            f"\nWARNING: cited passages that were never supplied: {integ['dangling_citations']}",
            file=sys.stderr,
        )
    if integ.get("claims_sufficient_without_citations"):
        print("\nWARNING: claimed sufficient context but cited nothing.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="incident-copilot")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--corpus", default=str(DEFAULT_CORPUS))
        sp.add_argument("--queries", default=str(DEFAULT_QUERIES))
        sp.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=["fixed", "sentence", "section"])
        sp.add_argument("--size", type=int, default=DEFAULT_SIZE)
        # Defaults to the sweep's size-scaled overlap, so the configuration
        # you evaluate is one the ablation actually measured.
        sp.add_argument("--overlap", type=int, default=None)
        sp.add_argument("--retriever", default=DEFAULT_RETRIEVER, choices=list(RETRIEVERS))
        sp.add_argument("-k", type=int, default=5)

    sp = sub.add_parser("ablate", help="sweep chunking x retriever (offline, free)")
    sp.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    sp.add_argument("--queries", default=str(DEFAULT_QUERIES))
    sp.add_argument("--metric", default="recall_at_3")
    sp.add_argument("--out", default=str(ROOT / "results"))
    sp.set_defaults(fn=_cmd_ablate)

    sp = sub.add_parser("evaluate", help="score one retrieval config (offline, free)")
    common(sp)
    sp.set_defaults(fn=_cmd_evaluate)

    sp = sub.add_parser("retrieve", help="show what would be retrieved (offline, free)")
    common(sp)
    sp.add_argument("query")
    sp.set_defaults(fn=_cmd_retrieve)

    sp = sub.add_parser("ask", help="retrieve, then generate a cited answer (calls the API)")
    common(sp)
    sp.add_argument("query")
    sp.add_argument("--model", default="claude-opus-5")
    sp.set_defaults(fn=_cmd_ask)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
