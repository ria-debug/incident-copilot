# What the ablation found

Every result here comes from `incident-copilot ablate` — 75 configurations over 25 labelled queries, reproducible offline in about a second. Raw data is in `results/ablation.json`, generated 2026-08-06 and extended with dense retrieval on 2026-09-01, re-verified by CI on every push: if the sweep stops reproducing these numbers, the build fails.

Three of my four going-in hypotheses were wrong. That is the useful part of this document.

Findings 1–5 are the original lexical sweep. Findings 6 and 7 come from adding a dense retriever, which findings 1 and 4 both predicted something about — one of those predictions held and the other one exposed finding 1 as conditional on the retriever.

---

## 1. Section-aware chunking underperforms, and the chunk-count column explains why

I expected splitting on markdown headings to beat arbitrary boundaries. Operational documents *are* written in retrievable units — one heading is one procedure — so honouring the author's structure should have won.

Averaged across every size and **lexical** retriever, it came last:

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

**Update (finding 7): this result is conditional on the retriever, and I did not know that when I wrote it.** The stated mechanism — fragments too short for BM25 to score confidently — predicts that a retriever which *can* score short text should reverse the ordering. Adding a dense retriever reversed it.

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

**Update: this finding made a falsifiable prediction, and finding 6 is the experiment that tested it.** The prediction held — fusion paid, and paid substantially, once the two retrievers actually failed differently. This is the only prediction in this document that survived contact with data.

## 5. A single metric is not enough to pick a retriever

The top result by recall@3 is not the best retriever:

| config | R@3 | MRR | R@5 |
|---|---:|---:|---:|
| fixed/120/bm25_expanded | **0.913** | 0.853 | 0.927 |
| sentence/180/bm25 | 0.887 | **0.908** | **0.980** |

`fixed/120` wins the metric I originally sorted by, and loses on rank quality (MRR 0.853 vs 0.908) and on deep recall (0.927 vs 0.980). For an on-call engineer who reads the first result, MRR is closer to what actually matters than recall@3 is — a document retrieved at rank 4 has been recalled and, practically, missed.

Shipping `fixed/120` would have been defensible from the number I happened to sort by, and wrong. The default is `sentence/180/bm25`.

**Update: this recurred exactly once more, with dense retrieval in the sweep.** The recall@3 winner across all 75 cells is `fixed/180/hybrid_dense` (R@3 0.947). The shipped default is `sentence/180/hybrid_dense`, which is 0.034 behind on recall@3 and ahead by 0.080 on R@1 and 0.040 on MRR. Same trap, same resolution, second time of asking.

## 6. Dense retrieval loses on its own and wins decisively when fused

The limitation this document has carried since the first version was that everything is lexical, and BM25 cannot match a query that shares no vocabulary with a relevant document. Finding 4 predicted that fusion would start paying once the fused retrievers failed differently.

Both halves of that turned out to be worth measuring separately, because the dense retriever on its own is **worse** than the BM25 it was supposed to improve on. At `sentence/180`:

| retriever | R@1 | R@3 | R@5 | P@3 | MRR | nDCG@5 | zero-recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 0.627 | 0.887 | **0.980** | 0.547 | 0.908 | 0.895 | 0 |
| dense | 0.667 | 0.800 | 0.813 | 0.560 | 0.920 | 0.812 | **1** |
| hybrid_dense | **0.747** | **0.913** | 0.960 | **0.587** | **0.973** | **0.929** | 0 |

Dense alone trades away 0.167 of recall@5 and introduces a zero-recall query — the failure mode this repo tracks separately precisely because averages hide it. What it buys is the top of the ranking: R@1 0.667 against 0.627, MRR 0.920 against 0.908. It is better at *ordering* and worse at *reaching*, which is the documented behaviour of embedding retrieval on a small corpus and still not what I expected to see on my own data.

Fused with BM25, every column moves the right way at once. **MRR 0.908 → 0.973** is the largest single improvement anywhere in this document, and it comes from combining two retrievers that individually rank first or second on nothing in particular.

Marginal means across all 75 cells make the same point without leaning on one cell:

| retriever | mean R@3 | mean MRR | mean R@1 | cells with a zero-recall query |
|---|---:|---:|---:|---:|
| bm25 | 0.853 | 0.851 | 0.565 | 8 |
| bm25_expanded | 0.849 | 0.879 | 0.597 | 5 |
| hybrid_rrf | 0.851 | 0.868 | 0.579 | 8 |
| dense | 0.852 | 0.908 | 0.654 | 6 |
| hybrid_dense | **0.893** | **0.928** | **0.660** | **0** |

Dense alone averages 0.852 on recall@3, which is a tie with plain BM25 to within a fifth of one query. Fusing them is worth +0.040 — ten times the gap between any two lexical retrievers in this sweep. That is finding 4's prediction, confirmed: **the value was never in the embedding, it was in the disagreement.**

The last column is the one I would lead with in an incident context. `hybrid_dense` is the only retriever in the sweep with **no configuration anywhere** that leaves a query with nothing relevant in its top 5. BM25 has eight.

**Why there is no vector database.** The corpus is 12 documents — 24 chunks at the shipped configuration, 70 at the most fragmented. Cosine similarity is a 70×256 matmul; an ANN index solves a problem that begins several orders of magnitude further up. The whole 75-cell sweep still runs offline in about a second, because the vectors are committed (`embeddings/vectors.npz`, 316 KB) rather than computed. Adding FAISS here would be a moving part added to look serious rather than to answer a question.

## 7. The best chunking strategy depends on the retriever, which one sweep could never have shown

Finding 1 concluded that section-aware chunking came last, and explained why: it produced 70 chunks averaging 39.7 words, and BM25 cannot score confidently on fragments that small.

That explanation is a prediction. If the problem is that *BM25* cannot score short fragments, then a retriever that can should reverse the result. Splitting the strategy marginals by retriever family:

| strategy | mean R@3, lexical retrievers | mean R@3, dense retrievers |
|---|---:|---:|
| sentence | **0.862** | 0.860 |
| fixed | 0.852 | 0.858 |
| section | 0.838 *(worst)* | **0.900** *(best)* |

Section chunking goes from last to first, and it is not close — +0.062 over its own lexical score, while `sentence` and `fixed` barely move. Short, heading-scoped fragments are bad evidence for a bag-of-words scorer with length normalisation and good evidence for an embedding, which encodes a 40-word procedure into the same 256 dimensions as a 400-word one.

Two things follow, and the second one is why this is written up separately.

**The mechanism in finding 1 was right.** I guessed at *why* section chunking lost, and the guess made a prediction that later data confirmed. That is a better outcome than the ranking itself.

**The conclusion in finding 1 was over-general, and nothing in the original sweep could have caught it.** "Section chunking underperforms" is not a property of the chunking strategy. It is a property of the pair (chunking strategy, retriever), and a sweep containing only lexical retrievers cannot distinguish those two claims — every cell in it agrees. The interaction only becomes visible when the sweep contains a retriever that fails differently, which is the same condition finding 4 identified for fusion, arriving from a completely different direction.

I do not think I would have found this by adding more sizes, more queries, or more lexical retrievers. It needed a genuinely different kind of retriever in the grid.


---

## Open questions and known limits

- **The embeddings are static, not contextual.** `potion-base-8M` is a distilled model whose inference is a token lookup and a mean, chosen so the sweep stays offline, free and byte-reproducible on any machine. It has no attention and no word-sense disambiguation, so "pool" as in connection pool and "pool" as in thread pool embed identically. A transformer encoder would very likely score better and would cost the reproducibility guarantee that makes this sweep get re-run at all — that is a trade I made deliberately and have not measured the size of.
- **Vectors are committed, so novel queries are the only path that runs the model.** `ablate` and `evaluate` read `embeddings/vectors.npz`; `retrieve` and `ask` encode whatever you type on first use. Editing the corpus without re-running `scripts/build_embeddings.py` therefore raises rather than silently scoring stale vectors, and a test asserts the committed cache covers every text the sweep asks for.
- **No reranker, and no attempt at one.** The obvious next step after fusion is a cross-encoder over the fused top-k. It is not built, and unlike dense retrieval I have no prediction about whether it would pay.
- **25 queries is a small set.** A 0.02 difference in recall@3 is half a query. I have leaned on marginal means over 75 cells rather than single-cell comparisons for exactly this reason, but the honest read is that findings 1, 5 and 6 are solid, finding 7 rests on a 0.062 marginal gap which is about one and a half queries, and the recall@5 detail in finding 3 is one query.
- **The corpus is synthetic and I wrote both sides.** I wrote the documents and the queries, so I know what the answer is, which biases query phrasing toward retrievability even when I am trying to avoid it. Findings about *relative* configuration performance survive this better than the absolute numbers do — treat R@3 ≈ 0.89 as a property of this corpus, not a claim about production.
- **Generation quality is unmeasured.** Retrieval is measured properly; the answer step has structural integrity checks (`answer.verify`) but no faithfulness eval. Whether the model actually stays inside the passages is checked structurally, not semantically.
- **Abstention is implemented, not evaluated.** Three unanswerable queries exist and the prompt has a real abstention path, but there is no scored metric for how often the system correctly says "I don't know".
