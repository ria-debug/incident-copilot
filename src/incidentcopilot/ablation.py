"""Sweeps chunking × retriever and reports what actually moved the numbers.

This is the module that distinguishes this from a tutorial RAG. Everyone picks a
chunk size; almost nobody measures whether it was the right one. The sweep runs
entirely offline on BM25, so re-running it after any corpus or chunking change
costs nothing and takes a second — which is the only reason it gets re-run.

Read `FINDINGS.md` for what the sweep actually found, including the two results
that contradicted what I expected going in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chunking import Strategy
from .corpus import Document, build_chunks
from .evaluate import Query, evaluate_retrieval
from .retrieval import RETRIEVERS, build_retriever

STRATEGIES: tuple[Strategy, ...] = ("fixed", "sentence", "section")
SIZES: tuple[int, ...] = (80, 120, 180, 260, 400)
OVERLAP_RATIO = 0.22


def default_overlap(size: int, *, overlap_ratio: float = OVERLAP_RATIO) -> int:
    """Overlap for a chunk size, used by both the sweep and the CLI.

    Scales with size rather than staying fixed. A constant 40-word overlap is
    50% of an 80-word chunk and 10% of a 400-word one, which would confound the
    size variable with an overlap variable and make the whole sweep
    uninterpretable. The CLI shares it so that the configuration you evaluate is
    a configuration the ablation actually measured.
    """
    return max(1, int(size * overlap_ratio))


def chunk_configs(
    *,
    strategies: tuple[Strategy, ...] = STRATEGIES,
    sizes: tuple[int, ...] = SIZES,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[tuple[Strategy, int, int]]:
    """Every (strategy, size, overlap) the sweep will build chunks for.

    Shared with `scripts/build_embeddings.py` so the embedding cache is built
    over exactly the chunk texts the sweep will ask for. If the two computed
    overlap independently, a size change here would leave the dense retriever
    silently uncovered for one row of the sweep.
    """
    return [
        (s, n, default_overlap(n, overlap_ratio=overlap_ratio))
        for s in strategies
        for n in sizes
    ]


@dataclass
class Cell:
    strategy: str
    size: int
    retriever: str
    n_chunks: int
    mean_chunk_words: float
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.strategy}/{self.size}/{self.retriever}"


def sweep(
    docs: list[Document],
    queries: list[Query],
    *,
    strategies: tuple[Strategy, ...] = STRATEGIES,
    sizes: tuple[int, ...] = SIZES,
    retrievers: tuple[str, ...] = RETRIEVERS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[Cell]:
    cells: list[Cell] = []
    for strategy, size, overlap in chunk_configs(
        strategies=strategies, sizes=sizes, overlap_ratio=overlap_ratio
    ):
        chunks = build_chunks(docs, strategy=strategy, size=size, overlap=overlap)
        mean_words = sum(c.n_words for c in chunks) / len(chunks) if chunks else 0.0
        for name in retrievers:
            report = evaluate_retrieval(build_retriever(name, chunks), queries, k=5)
            cells.append(
                Cell(
                    strategy=strategy,
                    size=size,
                    retriever=name,
                    n_chunks=len(chunks),
                    mean_chunk_words=round(mean_words, 1),
                    metrics=report.to_dict(),
                )
            )
    return cells


def best(cells: list[Cell], metric: str = "recall_at_3") -> Cell:
    # Ties break toward fewer chunks: same recall from a coarser index means
    # less context shipped to the model per query, which is cheaper and less
    # distracting for it.
    return max(cells, key=lambda c: (c.metrics.get(metric, 0.0), -c.n_chunks))


def marginals(cells: list[Cell], metric: str = "recall_at_3") -> dict[str, dict[str, float]]:
    """Mean metric per level of each variable.

    Reported because the single best cell is the one most likely to be noise on
    a set this size. If `section` beats `fixed` averaged across every size and
    retriever, that is a finding; one lucky cell is not.
    """
    out: dict[str, dict[str, float]] = {"strategy": {}, "size": {}, "retriever": {}}
    for dim, attr in (("strategy", "strategy"), ("size", "size"), ("retriever", "retriever")):
        buckets: dict[str, list[float]] = {}
        for c in cells:
            buckets.setdefault(str(getattr(c, attr)), []).append(c.metrics.get(metric, 0.0))
        out[dim] = {k: round(sum(v) / len(v), 4) for k, v in sorted(buckets.items())}
    return out


def render_markdown(cells: list[Cell], *, metric: str = "recall_at_3", top: int = 12) -> str:
    ranked = sorted(cells, key=lambda c: -c.metrics.get(metric, 0.0))
    champion = best(cells, metric)
    marg = marginals(cells, metric)

    lines = [
        "# Chunking / retriever ablation",
        "",
        (
            f"{len(cells)} configurations · {cells[0].metrics['n_queries']} answerable queries · "
            f"ranked by `{metric}`"
        ),
        "",
        (
            f"**Best:** `{champion.key}` — {metric} {champion.metrics[metric]:.3f}, "
            f"MRR {champion.metrics['mrr']:.3f}, {champion.n_chunks} chunks"
        ),
        "",
        "## Marginal means (averaged over the other variables)",
        "",
    ]
    for dim, values in marg.items():
        row = " · ".join(f"`{k}` {v:.3f}" for k, v in values.items())
        lines.append(f"- **{dim}** — {row}")
    lines += [
        "",
        f"## Top {top} configurations",
        "",
        "| config | chunks | mean words | R@1 | R@3 | R@5 | P@3 | MRR | nDCG@5 | zero-recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in ranked[:top]:
        m = c.metrics
        lines.append(
            f"| `{c.key}` | {c.n_chunks} | {c.mean_chunk_words:.0f} | "
            f"{m['recall_at_1']:.3f} | {m['recall_at_3']:.3f} | {m['recall_at_5']:.3f} | "
            f"{m['precision_at_3']:.3f} | {m['mrr']:.3f} | {m['ndcg_at_5']:.3f} | "
            f"{m['n_zero_recall']} |"
        )
    lines += [
        "",
        "## Worst 3",
        "",
        "| config | R@3 | MRR | zero-recall |",
        "| --- | ---: | ---: | ---: |",
    ]
    for c in ranked[-3:]:
        m = c.metrics
        lines.append(f"| `{c.key}` | {m['recall_at_3']:.3f} | {m['mrr']:.3f} | {m['n_zero_recall']} |")
    lines.append("")
    return "\n".join(lines)


def write_results(cells: list[Cell], out_dir: Path, *, metric: str = "recall_at_3") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ablation.md").write_text(render_markdown(cells, metric=metric), encoding="utf-8")
    (out_dir / "ablation.json").write_text(
        json.dumps([c.__dict__ for c in cells], indent=2), encoding="utf-8"
    )
