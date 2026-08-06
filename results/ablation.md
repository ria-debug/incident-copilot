# Chunking / retriever ablation

45 configurations · 25 answerable queries · ranked by `recall_at_3`

**Best:** `fixed/120/bm25_expanded` — recall_at_3 0.913, MRR 0.853, 32 chunks

## Marginal means (averaged over the other variables)

- **strategy** — `fixed` 0.852 · `section` 0.838 · `sentence` 0.862
- **size** — `120` 0.862 · `180` 0.863 · `260` 0.843 · `400` 0.843 · `80` 0.844
- **retriever** — `bm25` 0.853 · `bm25_expanded` 0.849 · `hybrid_rrf` 0.851

## Top 12 configurations

| config | chunks | mean words | R@1 | R@3 | R@5 | P@3 | MRR | nDCG@5 | zero-recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `fixed/120/bm25_expanded` | 32 | 106 | 0.527 | 0.913 | 0.927 | 0.613 | 0.853 | 0.827 | 0 |
| `sentence/180/bm25` | 24 | 119 | 0.627 | 0.887 | 0.980 | 0.547 | 0.908 | 0.895 | 0 |
| `sentence/180/bm25_expanded` | 24 | 119 | 0.627 | 0.887 | 0.960 | 0.560 | 0.910 | 0.886 | 0 |
| `sentence/180/hybrid_rrf` | 24 | 119 | 0.627 | 0.887 | 0.980 | 0.560 | 0.908 | 0.895 | 0 |
| `fixed/120/bm25` | 32 | 106 | 0.507 | 0.873 | 0.927 | 0.600 | 0.828 | 0.811 | 0 |
| `fixed/120/hybrid_rrf` | 32 | 106 | 0.527 | 0.873 | 0.927 | 0.600 | 0.850 | 0.822 | 0 |
| `sentence/80/bm25_expanded` | 46 | 62 | 0.607 | 0.873 | 0.947 | 0.587 | 0.863 | 0.855 | 0 |
| `sentence/80/hybrid_rrf` | 46 | 62 | 0.567 | 0.873 | 0.893 | 0.587 | 0.833 | 0.819 | 1 |
| `fixed/180/bm25` | 24 | 139 | 0.607 | 0.867 | 0.940 | 0.573 | 0.881 | 0.855 | 0 |
| `fixed/180/bm25_expanded` | 24 | 139 | 0.627 | 0.867 | 0.940 | 0.587 | 0.901 | 0.864 | 0 |
| `fixed/180/hybrid_rrf` | 24 | 139 | 0.627 | 0.867 | 0.940 | 0.587 | 0.901 | 0.864 | 0 |
| `sentence/120/bm25_expanded` | 32 | 90 | 0.627 | 0.867 | 0.927 | 0.587 | 0.883 | 0.857 | 0 |

## Worst 3

| config | R@3 | MRR | zero-recall |
| --- | ---: | ---: | ---: |
| `section/260/bm25_expanded` | 0.820 | 0.860 | 1 |
| `section/400/bm25_expanded` | 0.820 | 0.860 | 1 |
| `fixed/80/bm25` | 0.807 | 0.840 | 1 |
