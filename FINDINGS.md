# What the ablation found

Every result here comes from `incident-copilot ablate` — 45 configurations over 25 labelled queries, reproducible offline in about a second. Raw data is in `results/ablation.json`, generated 2026-08-06 and re-verified by CI on every push: if the sweep stops reproducing these numbers, the build fails.

Three of my four going-in hypotheses were wrong. That is the useful part of this document.

---

## 1. Section-aware chunking underperforms, and the chunk-count column explains why

I expected splitting on markdown headings to beat arbitrary boundaries. Operational documents *are* written in retrievable units — one heading is one procedure — so honouring the author's structure should have won.

Averaged across every size and retriever, it came last:

| strategy | mean recall@3 |
|---|---|
| sentence | **0.862** |
| fixed | 0.852 |
| section | 0.838 |

Head-to-head at size 180 with BM25, the gap is wider than the average suggests:

| strategy | chunks | mean words | R@3 | R@5 | MRR | zero-recall |
|---|---:|---:|---:|---:|---:|---:|
| sentence | 24 | 119.3 | **0.887** | **0.980** | **0.908** | 0 |
| fixed | 24 | 138.8 | 0.867 | 0.940 | 0.881 | 0 |
| section | 70 | 39.7 | 0.853 | 0.867 | 0.820 | **1** |

**The diagnosis is in the chunk-count column.** Section chunking produced 70 chunks averaging 39.7 words, against 24 chunks averaging 119. My corpus has far more headings than I was picturing, so "respect the structure" turned into "shatter every document into fragments". Each fragment carries too few terms for BM25 to score confidently, and length normalisation then treats a 20-word fragment and a 200-word procedure as comparable evidence. That is also where the single zero-recall query comes from.

The lesson generalises past this corpus: a chunking strategy is a claim about *document structure*, and it is only as good as that claim. My claim was true about the documents I imagined and false about the ones I wrote.

## 2. The `size` parameter is inert for section chunking above 120 words

| size | chunks | mean words | R@3 | MRR |
|---:|---:|---:|---:|---:|
| 80 | 72 | 38.7 | 0.853 | 0.813 |
| 120 | 70 | 39.7 | 0.853 | 0.820 |
| 180 | 70 | 39.7 | 0.853 | 0.820 |
| 260 | 70 | 39.7 | 0.853 | 0.820 |
| 400 | 70 | 39.7 | 0.853 | 0.820 |

Identical from 120 words upward. `size` is only a *ceiling* in `chunk_section` — it triggers the sentence-packing fallback for oversized sections — and above 120 words almost no section in this corpus is large enough to hit it. So the knob is inert across most of its range.

I would not have caught this by reading the code; it looks like it works. I caught it because the sweep printed five identical rows, which is a thing only a sweep does. Had I tuned section chunking by hand I would have concluded the size was well-chosen, when in fact it was never being applied.

## 3. Domain query expansion trades recall for precision

I hand-built a synonym map — "slow" → latency/p99/degraded, "stuck" → deadlock/blocked/timeout — expecting it to bridge the gap between how engineers type and how docs are written. At the winning config:

| retriever | R@1 | R@3 | R@5 | MRR | P@3 |
|---|---:|---:|---:|---:|---:|
| bm25 | 0.627 | 0.887 | **0.980** | 0.908 | 0.547 |
| bm25_expanded | 0.627 | 0.887 | 0.960 | **0.910** | **0.560** |

Recall@3 identical. **Recall@5 got worse** (0.980 → 0.960) — expansion terms pulled a genuinely relevant document out of the top 5 in one query. What it bought was a rounding error on MRR and a real but small gain on precision@3.

The trade is coherent in hindsight: expansion sharpens the top of the ranking and blurs the tail. But I built it expecting a recall win, and it delivered the opposite. Averaged across all 45 cells, expansion is *behind* plain BM25 (0.849 vs 0.853).

## 4. Hybrid rank fusion adds cost without adding signal

Reciprocal-rank fusion over BM25 + expanded-BM25 matched plain BM25 exactly on R@1, R@3, R@5, and MRR at the winning config, differing only on precision@3 (0.560 vs 0.547). Marginal means across the whole sweep: bm25 0.853, hybrid_rrf 0.851.

Fusion helps when the fused retrievers fail *differently*. Mine were BM25 and BM25-with-extra-terms — the same scoring function over near-identical term sets, so they agree on nearly everything and there is nothing for fusion to reconcile. Real diversity would mean a dense retriever alongside a lexical one, which is the obvious next experiment and is not built.

**The default is now plain BM25.** The simplest of the three retrievers, chosen because the data gave no reason to pay for either of the others.

## 5. A single metric is not enough to pick a retriever

The top result by recall@3 is not the best retriever:

| config | R@3 | MRR | R@5 |
|---|---:|---:|---:|
| fixed/120/bm25_expanded | **0.913** | 0.853 | 0.927 |
| sentence/180/bm25 | 0.887 | **0.908** | **0.980** |

`fixed/120` wins the metric I originally sorted by, and loses on rank quality (MRR 0.853 vs 0.908) and on deep recall (0.927 vs 0.980). For an on-call engineer who reads the first result, MRR is closer to what actually matters than recall@3 is — a document retrieved at rank 4 has been recalled and, practically, missed.

Shipping `fixed/120` would have been defensible from the number I happened to sort by, and wrong. The default is `sentence/180/bm25`.

---

## Open questions and known limits

- **No dense retrieval.** Everything here is lexical. The failure mode BM25 cannot fix is a query sharing no vocabulary with a relevant document, and my synonym map is a manual patch over that gap rather than a solution. An embedding retriever is the highest-value next experiment, and finding 4 predicts fusion would actually pay once the retrievers fail differently.
- **25 queries is a small set.** A 0.02 difference in recall@3 is half a query. I have leaned on marginal means over 45 cells rather than single-cell comparisons for exactly this reason, but the honest read is that findings 1 and 5 are solid and the recall@5 detail in finding 3 is one query.
- **The corpus is synthetic and I wrote both sides.** I wrote the documents and the queries, so I know what the answer is, which biases query phrasing toward retrievability even when I am trying to avoid it. Findings about *relative* configuration performance survive this better than the absolute numbers do — treat R@3 ≈ 0.89 as a property of this corpus, not a claim about production.
- **Generation quality is unmeasured.** Retrieval is measured properly; the answer step has structural integrity checks (`answer.verify`) but no faithfulness eval. Whether the model actually stays inside the passages is checked structurally, not semantically.
- **Abstention is implemented, not evaluated.** Three unanswerable queries exist and the prompt has a real abstention path, but there is no scored metric for how often the system correctly says "I don't know".
