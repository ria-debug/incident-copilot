"""Loads the markdown corpus and builds an index for a given chunking config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chunking import Chunk, Strategy, chunk_document


@dataclass
class Document:
    doc_id: str
    kind: str  # runbook | postmortem | reference
    title: str
    text: str
    path: Path


def load_corpus(root: Path) -> list[Document]:
    docs: list[Document] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8")
        first = next((ln for ln in text.splitlines() if ln.startswith("# ")), "")
        docs.append(
            Document(
                doc_id=path.stem,
                kind=path.parent.name.rstrip("s") or "reference",
                title=first.lstrip("# ").strip() or path.stem,
                text=text,
                path=path,
            )
        )
    if not docs:
        raise ValueError(f"no markdown documents under {root}")
    return docs


def build_chunks(
    docs: list[Document], *, strategy: Strategy = "section", size: int = 180, overlap: int = 40
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for d in docs:
        chunks.extend(
            chunk_document(
                d.doc_id,
                d.text,
                strategy=strategy,
                size=size,
                overlap=overlap,
                meta={"kind": d.kind, "title": d.title},
            )
        )
    return chunks
