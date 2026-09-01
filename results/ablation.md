# Chunking / retriever ablation

75 configurations · 25 answerable queries · ranked by `recall_at_3`

**Best:** `fixed/180/hybrid_dense` — recall_at_3 0.947, MRR 0.933, 24 chunks

## Marginal means (averaged over the other variables)

- **strategy** — `fixed` 0.855 · `section` 0.863 · `sentence` 0.861
- **size** — `120` 0.867 · `180` 0.870 · `260` 0.852 · `400` 0.852 · `80` 0.857
- **retriever** — `bm25` 0.853 · `bm25_expanded` 0.849 · `dense` 0.852 · `hybrid_dense` 0.893 · `hybrid_rrf` 0.851

## Top 12 configurations

| config | chunks | mean words | R@1 | R@3 | R@5 | P@3 | MRR | nDCG@5 | zero-recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `fixed/180/hybrid_dense` | 24 | 139 | 0.667 | 0.947 | 0.960 | 0.693 | 0.933 | 0.900 | 0 |
| `fixed/120/bm25_expanded` | 32 | 106 | 0.527 | 0.913 | 0.927 | 0.613 | 0.853 | 0.827 | 0 |
| `sentence/180/hybrid_dense` | 24 | 119 | 0.747 | 0.913 | 0.960 | 0.587 | 0.973 | 0.929 | 0 |
| `sentence/260/hybrid_dense` | 15 | 191 | 0.587 | 0.907 | 0.980 | 0.440 | 0.893 | 0.879 | 0 |
| `section/80/hybrid_dense` | 72 | 39 | 0.687 | 0.907 | 0.920 | 0.693 | 0.940 | 0.896 | 0 |
| `section/120/hybrid_dense` | 70 | 40 | 0.687 | 0.907 | 0.940 | 0.707 | 0.940 | 0.905 | 0 |
| `section/180/hybrid_dense` | 70 | 40 | 0.687 | 0.907 | 0.940 | 0.707 | 0.940 | 0.905 | 0 |
| `section/260/hybrid_dense` | 70 | 40 | 0.687 | 0.907 | 0.940 | 0.707 | 0.940 | 0.905 | 0 |
| `section/400/hybrid_dense` | 70 | 40 | 0.687 | 0.907 | 0.940 | 0.707 | 0.940 | 0.905 | 0 |
| `sentence/80/hybrid_dense` | 46 | 62 | 0.667 | 0.893 | 0.933 | 0.667 | 0.933 | 0.888 | 0 |
| `section/80/dense` | 72 | 39 | 0.627 | 0.893 | 0.893 | 0.693 | 0.893 | 0.836 | 0 |
| `section/120/dense` | 70 | 40 | 0.627 | 0.893 | 0.893 | 0.693 | 0.893 | 0.840 | 0 |

## Worst 3

| config | R@3 | MRR | zero-recall |
| --- | ---: | ---: | ---: |
| `sentence/400/dense` | 0.813 | 0.920 | 1 |
| `fixed/80/bm25` | 0.807 | 0.840 | 1 |
| `sentence/180/dense` | 0.800 | 0.920 | 1 |
