# incident-copilot

[![ci](https://github.com/ria-debug/incident-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/ria-debug/incident-copilot/actions/workflows/ci.yml)

**RAG over operational documentation, measured before it is trusted.**

Most RAG projects pick a chunk size, wire up a vector store, and ship. This one starts from the opposite assumption: a system that answers fluently from the wrong three passages looks identical to one that works, right up until an on-call engineer runs the wrong command at 3am. So retrieval is scored on its own — recall, precision, MRR, nDCG — before any model sees a passage.

```
                                    ┌──────────────────────────┐
 corpus ──▶ chunk ──▶ retrieve ──┬─▶│ 25 labelled queries      │──▶ recall · precision
 12 docs    3 ways    lexical    │  │ scored on their own      │    MRR · nDCG
                      + dense    │  └──────────────────────────┘    zero-recall
                      fused      │        the gate: a passage never retrieved
                                 │        cannot be recovered downstream
                                 ▼
                            generate ──▶ verify ──▶ answer + citations
                            cited,       structural,   or "insufficient
                            grounded     no 2nd call    context"
```

CI re-runs the whole sweep on every push and fails if the committed results stop reproducing — the measurement is enforced, not asserted.

```
$ incident-copilot retrieve "api is slow but cpu and memory look fine"

[1] api-latency-degradation           score=0.033
[2] connection-pool-exhaustion        score=0.033
[3] 2026-03-14-payments-degradation   score=0.031
```

Both of the first two are labelled relevant for that query, and the query never says "pool" or "latency degradation". Getting that right is a retrieval property, and no amount of prompt engineering downstream can recover a passage that was never retrieved.

---

## The part worth reading: [FINDINGS.md](FINDINGS.md)

Three of my four going-in hypotheses were wrong, and the ablation is what caught them:

- **Section-aware chunking — my main hypothesis — ranked last of three.** It fragmented the corpus into 70 chunks averaging 39 words instead of 24 averaging 119, and BM25 cannot score confidently on fragments that small.
- **The `size` parameter does nothing for section chunking.** Identical results from 120 words to 400. It is only a ceiling, and almost no section is large enough to hit it. Five identical rows in a sweep is a thing only a sweep shows you; by hand I would have concluded the size was well-chosen.
- **Domain query expansion traded recall for precision** — recall@5 moved 0.980 → 0.960 while precision@3 improved. I built it expecting the opposite.
- **Hybrid rank fusion added cost without signal** — identical to plain BM25 on every metric but one. Fusion needs retrievers that fail *differently*; mine were BM25 and BM25-with-extra-terms.
- **Sorting on recall@3 alone would have shipped the worse retriever** — the R@3 winner is 0.055 behind on MRR, which is closer to what matters for someone who reads the first result.

Adding a dense retriever later tested two of those findings against new data, and they came apart in opposite directions:

- **The dense retriever is worse than BM25 on its own** — recall@5 0.813 against 0.980, and it introduces a zero-recall query. Fused with BM25 it takes **MRR 0.908 → 0.973** and is the only retriever in the sweep with no zero-recall configuration anywhere. Finding 4 predicted exactly this: the value is in the disagreement, not the embedding.
- **"Section chunking underperforms" turned out to be a claim about BM25, not about chunking.** Split by retriever family, section goes from worst on lexical (0.838) to best on dense (0.900). The mechanism I guessed in finding 1 was right; the conclusion I drew from it was over-general, and no sweep made only of lexical retrievers could have shown that.

The shipped default is `sentence/180/hybrid_dense`, chosen by the sweep rather than by taste — and, for the second time in this project, it is *not* the top cell by recall@3.

---

## Measured retrieval

75 configurations (3 chunking strategies × 5 sizes × 5 retrievers) over 25 labelled queries. The sweep runs offline in about a second — the dense retriever reads committed vectors rather than loading a model — which is the only reason it actually gets re-run after a corpus change:

```
$ incident-copilot ablate
```

Current default config — `sentence/180/hybrid_dense`, re-verified by CI on every push. The `bm25` column is the previous default, kept alongside because the interesting number is the delta:

| metric | bm25 (was) | hybrid_dense (now) |
|---|---:|---:|
| recall@1 | 0.627 | **0.747** |
| recall@3 | 0.887 | **0.913** |
| recall@5 | **0.980** | 0.960 |
| precision@3 | 0.547 | **0.587** |
| MRR | 0.908 | **0.973** |
| nDCG@5 | 0.895 | **0.929** |
| zero-recall queries | 0 | 0 |

Recall@5 is the one column that got worse, and it is left in rather than dropped: fusion reorders, and reordering can push a deep result out of the top 5.

**Zero-recall count is tracked separately from the averages.** Twenty queries at 0.9 and four at 0.0 average to a healthy number, and those four are the incidents where the tool is worse than useless.

**Relevance is judged per document, not per chunk** — deliberately. Chunk-level labels would need redoing for every ablation cell, which would make the thing being varied also the thing being measured against.

Queries are phrased the way an engineer types mid-incident ("a bunch of different pods restarted on the same node"), not the way documents are titled. A query set written in the corpus's own vocabulary measures string matching and flatters any retriever.

---

## Grounded answers

Retrieval feeds a generation step with two non-negotiable properties:

**Every claim carries a citation** — not for the appearance of rigour, but because the useful output during an incident is "open runbook X, section Y". An engineer must verify advice against the source before running a command against production.

**Abstention is a success, not a fallback.** `sufficient_context: false` is a first-class outcome. Three queries in the eval set are deliberately unanswerable. A tool that invents a plausible procedure for an uncovered failure is worse than no tool: confidently wrong at the exact moment nobody has time to check.

Answers are then checked **structurally, with no second model call** — `answer.verify()` catches citations pointing at passages that were never supplied, answers claiming sufficient context while citing nothing, and answers that abstain and then answer anyway. These are contradictions visible from the structure alone, which makes them cheap enough to run on every answer.

```bash
incident-copilot ask "connection pool is saturated, what do I check first"
```

---

## Honest limitations

- **The embeddings are static, not contextual.** `potion-base-8M` distils a sentence transformer down to a token lookup and a mean — no attention, so "pool" as in connection pool and "pool" as in thread pool embed identically. It was chosen so the 75-cell sweep stays offline, free and byte-identical on every machine. A real encoder would very likely score better and would cost that guarantee; I have not measured how much better.
- **There is no vector database, deliberately.** 24 chunks at the shipped config, 70 at the most fragmented. Cosine similarity is a 70×256 matmul, and an ANN index solves a problem that starts several orders of magnitude further up.
- **No reranker.** A cross-encoder over the fused top-k is the obvious next step, and unlike dense retrieval I have no prediction about whether it would pay.
- **25 queries is small.** A 0.02 difference in recall@3 is half a query. Findings lean on marginal means across 75 cells rather than single-cell comparisons for that reason.
- **The corpus is synthetic and I wrote both sides.** Knowing the answers biases query phrasing toward retrievability even when trying to avoid it. Treat *relative* configuration results as the finding and the absolute numbers as a property of this corpus.
- **Generation is checked structurally, not semantically.** There is no faithfulness eval and no scored abstention metric.

The corpus is modelled on the shape of banking-API operational documentation — procedures whose bodies never repeat their own topic, postmortems that bury the cause three paragraphs in, two documents that partly contradict each other — but contains no real system, threshold, or incident.

---

## Usage

```bash
uv sync

incident-copilot ablate                      # sweep everything (offline, free)
incident-copilot evaluate                    # score the default config (offline, free)
incident-copilot retrieve "<query>"          # show what would be retrieved (free)
incident-copilot ask "<query>"               # cited answer (calls the API)

uv run pytest -q                             # 63 tests, offline
python scripts/build_corpus.py               # regenerate the corpus
python scripts/build_embeddings.py           # regenerate the committed vectors
```

Only `ask` needs `ANTHROPIC_API_KEY`. Override any part of the config with `--strategy`, `--size`, `--retriever`, `-k`.

`ablate` and `evaluate` never run the embedding model — they read `embeddings/vectors.npz`, which is what keeps them offline and byte-reproducible. `retrieve` and `ask` encode whatever query you type, so those two download the 30 MB model on first use. Edit the corpus and the eval path will *raise* rather than score stale vectors, telling you to re-run `scripts/build_embeddings.py`; a test asserts the committed cache covers every text the sweep asks for.

## Layout

```
src/incidentcopilot/
  chunking.py    fixed / sentence / section strategies
  retrieval.py   BM25, synonym-expanded BM25, dense, and two rank fusions
  embeddings.py  committed vectors keyed by content hash; live encode for novel queries
  evaluate.py    recall@k, precision@k, MRR, nDCG, zero-recall tracking
  ablation.py    the sweep, marginal means, and the results table
  answer.py      grounded generation, citations, abstention, integrity checks
corpus/          12 synthetic runbooks, postmortems, and reference pages
evaluation/      25 labelled queries + 3 deliberately unanswerable
embeddings/      vectors.npz — 323 vectors, 316 KB, regenerated by a script
results/         committed ablation output
```

## Licence

MIT
