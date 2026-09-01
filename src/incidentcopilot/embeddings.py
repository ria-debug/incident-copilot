"""Committed embedding vectors, keyed by the hash of the text they encode.

The whole repo rests on the ablation being cheap enough that it actually gets
re-run: 75 configurations, offline, in about a second, enforced by CI. A dense
retriever normally destroys that -- it wants a model download or a paid API on
every sweep, and it makes the numbers machine-dependent.

So the model never runs at evaluation time. `scripts/build_embeddings.py` encodes
every chunk the sweep can produce plus every labelled query, once, and commits
the vectors. `ablate`, `evaluate` and the tests then read a numpy array. CI never
downloads a model, never reaches the network, and gets byte-identical numbers on
every machine -- which is what lets it keep failing the build when the committed
results stop reproducing.

The cost of that trade is honest and worth stating: a query nobody has embedded
yet cannot be served from the cache. `retrieve` and `ask` therefore opt in to a
live fallback (`live=True`), which encodes whatever the user typed with the real
model on first use. `ablate` and `evaluate` never do -- there, a missing vector
means the corpus changed and the committed numbers are stale, and quietly
computing the vector would hide exactly that.

Missing vectors raise rather than degrade. A zero vector would score every chunk
identically and read as a weak result rather than a missing one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Static (distilled) embeddings rather than a transformer: inference is a token
# lookup and a mean, so regenerating needs no GPU, no torch, and no API key,
# and the vectors are bit-identical on every machine.
MODEL = "minishlab/potion-base-8M"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "embeddings" / "vectors.npz"


class MissingEmbeddings(RuntimeError):
    """Raised when a text has no committed vector.

    Deliberately fatal. The alternative -- returning zeros -- produces a
    retriever that ranks every chunk equally and looks merely bad rather than
    broken, which is the exact failure mode this project is about catching.
    """

    def __init__(self, missing: list[str]) -> None:
        shown = ", ".join(repr(m[:60]) for m in missing[:3])
        more = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
        super().__init__(
            f"{len(missing)} text(s) have no committed embedding: {shown}{more}. "
            f"Run `uv run python scripts/build_embeddings.py` to regenerate "
            f"the cache after a corpus, chunking or query-set change."
        )
        self.missing = missing


def text_key(text: str) -> str:
    """Content hash, so one cache serves every chunking configuration.

    Chunk ids encode strategy and position and therefore change in all 15 sweep
    configurations; the text of a chunk is the only stable identity it has.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class EmbeddingStore:
    model: str
    keys: list[str]
    matrix: np.ndarray  # (n, dim) float32, L2-normalised
    # Opt-in, never automatic. If this defaulted to True, the behaviour of the
    # eval path would depend on whether the optional group happened to be
    # installed -- precisely the environment-dependent result this repo exists
    # to avoid.
    live: bool = False

    def __post_init__(self) -> None:
        self._index = {k: i for i, k in enumerate(self.keys)}
        self._model = None

    @classmethod
    def from_vectors(
        cls, texts: list[str], vectors: np.ndarray, *, model: str, live: bool = False
    ) -> EmbeddingStore:
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        # A zero vector has no direction to normalise. Leaving it at zero makes
        # it score 0 against everything, which is the correct behaviour for text
        # the model had nothing to say about.
        matrix = matrix / np.where(norms == 0, 1.0, norms)
        return cls(model=model, keys=[text_key(t) for t in texts], matrix=matrix, live=live)

    def __contains__(self, key: str) -> bool:
        return key in self._index

    def covers(self, texts: list[str]) -> list[str]:
        """Texts with no vector. Used by the CI coverage test, which is what
        stops a corpus edit silently invalidating the committed numbers."""
        return [t for t in texts if text_key(t) not in self._index]

    def encode(self, texts: list[str]) -> np.ndarray:
        missing = self.covers(texts)
        if missing:
            if not self.live:
                raise MissingEmbeddings(missing)
            self._add(missing)
        return self.matrix[[self._index[text_key(t)] for t in texts]]

    def _add(self, texts: list[str]) -> None:
        """Encode and memoise in process.

        Never written back to the committed cache: that file is a build artefact
        of `scripts/build_embeddings.py`, and a query typed at a CLI is not part
        of the evaluated corpus.
        """
        if self._model is None:
            try:
                from model2vec import StaticModel
            except ImportError as e:
                raise MissingEmbeddings(texts) from e
            self._model = StaticModel.from_pretrained(self.model)
        vectors = np.asarray(self._model.encode(texts), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.where(norms == 0, 1.0, norms)
        for text in texts:
            self._index[text_key(text)] = len(self.keys)
            self.keys.append(text_key(text))
        self.matrix = np.vstack([self.matrix, vectors])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, model=np.array(self.model), keys=np.array(self.keys), matrix=self.matrix
        )

    @classmethod
    def load(cls, path: Path = DEFAULT_CACHE, *, live: bool = False) -> EmbeddingStore:
        if not path.exists():
            raise MissingEmbeddings([f"<no cache at {path}>"])
        with np.load(path, allow_pickle=False) as data:
            return cls(
                model=str(data["model"]),
                keys=[str(k) for k in data["keys"]],
                matrix=data["matrix"].astype(np.float32),
                live=live,
            )
