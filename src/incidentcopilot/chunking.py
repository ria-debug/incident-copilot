"""Chunking strategies — the variable most RAG projects never actually test.

The usual approach is to pick 512 tokens because a tutorial said so and never
revisit it. Chunk size and boundary policy are the highest-leverage retrieval
decisions available, and they interact: a size that works for prose destroys a
runbook whose value is in its numbered steps.

Three strategies are implemented so the ablation can measure the difference
rather than assume it:

* `fixed`     — N words, fixed overlap. The naive baseline everyone ships.
* `sentence`  — packs whole sentences up to a budget. Never splits mid-sentence.
* `section`   — splits on markdown headings, then packs oversized sections.
                Respects the document's own structure.

`section` is the hypothesis under test: operational documents are *written* in
retrievable units — one heading is one procedure — so honouring the author's
boundaries should beat imposing arbitrary ones. `ablation.py` checks whether
that is true rather than taking it on faith.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Strategy = Literal["fixed", "sentence", "section"]


@dataclass
class Chunk:
    """A retrievable unit.

    `doc_id` + `section` are what a citation points at. A chunk that cannot be
    cited back to a location in a real document is useless in an incident: an
    on-call engineer at 3am needs to open the runbook, not trust a paraphrase.
    """

    chunk_id: str
    doc_id: str
    text: str
    section: str = ""
    ordinal: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_words(self) -> int:
        return len(self.text.split())

    def citation(self) -> str:
        return f"{self.doc_id}#{self.section}" if self.section else self.doc_id


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def split_sentences(text: str) -> list[str]:
    """Deliberately regex-based, not an NLP dependency.

    Operational docs are full of abbreviations and version numbers that trip
    naive splitters, so this is imperfect — but it is deterministic, free, and
    the ablation measures whether the imperfection actually costs retrieval
    quality. See FAILURES.md; it turned out to matter less than chunk size.
    """
    parts = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _emit(chunks: list[Chunk], doc_id: str, section: str, words: list[str], meta: dict) -> None:
    if not words:
        return
    chunks.append(
        Chunk(
            chunk_id=f"{doc_id}::{len(chunks):03d}",
            doc_id=doc_id,
            text=" ".join(words),
            section=section,
            ordinal=len(chunks),
            meta=dict(meta),
        )
    )


def chunk_fixed(doc_id: str, text: str, *, size: int, overlap: int, meta: dict) -> list[Chunk]:
    words = text.split()
    if overlap >= size:
        raise ValueError("overlap must be smaller than size, or chunking never advances")
    out: list[Chunk] = []
    step = size - overlap
    for start in range(0, max(len(words), 1), step):
        window = words[start : start + size]
        if not window:
            break
        _emit(out, doc_id, "", window, meta)
        if start + size >= len(words):
            break
    return out


def chunk_sentence(doc_id: str, text: str, *, size: int, meta: dict) -> list[Chunk]:
    out: list[Chunk] = []
    buf: list[str] = []
    for sentence in split_sentences(text):
        words = sentence.split()
        # A single sentence longer than the budget is emitted whole rather than
        # split. Truncating it would lose exactly the kind of long procedural
        # line that runbooks are made of.
        if buf and len(buf) + len(words) > size:
            _emit(out, doc_id, "", buf, meta)
            buf = []
        buf.extend(words)
    _emit(out, doc_id, "", buf, meta)
    return out


def chunk_section(doc_id: str, text: str, *, size: int, meta: dict) -> list[Chunk]:
    """Split on markdown headings; pack oversized sections by sentence.

    Sections carry their heading into the chunk text. That is not cosmetic: a
    procedure body often never repeats its own topic ("Restart the pool, then
    verify"), so a chunk stripped of "## Connection pool exhaustion" is
    unretrievable by the words an engineer would actually search for.
    """
    out: list[Chunk] = []
    current_heading = ""
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        body = " ".join(buf)
        prefixed = f"{current_heading}. {body}" if current_heading else body
        if len(prefixed.split()) <= size:
            _emit(out, doc_id, current_heading, prefixed.split(), meta)
        else:
            packed: list[str] = []
            for sentence in split_sentences(body):
                words = sentence.split()
                if packed and len(packed) + len(words) > size:
                    _emit(out, doc_id, current_heading,
                          (f"{current_heading}. " if current_heading else "").split() + packed, meta)
                    packed = []
                packed.extend(words)
            if packed:
                _emit(out, doc_id, current_heading,
                      (f"{current_heading}. " if current_heading else "").split() + packed, meta)
        buf = []

    for line in text.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            flush()
            current_heading = m.group(2).strip()
            continue
        if line.strip():
            buf.extend(line.split())
    flush()
    return out


def chunk_document(
    doc_id: str,
    text: str,
    *,
    strategy: Strategy = "section",
    size: int = 180,
    overlap: int = 40,
    meta: dict | None = None,
) -> list[Chunk]:
    meta = meta or {}
    if strategy == "fixed":
        return chunk_fixed(doc_id, text, size=size, overlap=overlap, meta=meta)
    if strategy == "sentence":
        return chunk_sentence(doc_id, text, size=size, meta=meta)
    if strategy == "section":
        return chunk_section(doc_id, text, size=size, meta=meta)
    raise ValueError(f"unknown chunking strategy {strategy!r}")
