"""Retrieval over a business knowledge base, for spoken enquiries.

A business hands over a folder of plain-text facts - hours, policies, pricing,
returns, escalation rules - and the agent answers callers from it instead of
from the model's own memory.

Deliberately simple: TF-IDF-style scoring over sentence chunks, no embedding
service, no vector database. Retrieval quality is bounded and inspectable,
which is the point for a compliance-shaped deployment - every spoken answer can
be traced to the exact source line that produced it.

Grounding rule: if nothing scores above the floor, the agent says it does not
know and offers escalation. It never answers a business enquiry from parametric
memory, because a confident wrong answer about a refund policy is worse than
no answer.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KB_DIR = Path(__file__).parent / "kb"
SCORE_FLOOR = 0.12          # below this, we decline rather than guess
TOP_K = 3

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "it", "we", "you", "your", "our", "do", "does", "can", "i",
    "what", "how", "when", "where", "if", "at", "be", "with", "that", "this",
}


def read_document(path: Path) -> str:
    """Plain text from .md, .txt or .pdf. PDFs are extracted with pypdf; a
    scanned PDF with no text layer yields nothing and is reported as such."""
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        try:
            pages = [pg.extract_text() or "" for pg in PdfReader(str(path)).pages]
            return "\n\n".join(t.strip() for t in pages if t.strip())
        except Exception:
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


_UNSPEAKABLE = re.compile(r"[•●▪■‣⁃ ​﻿–—]")


def clean(text: str) -> str:
    """Strip characters that would be read aloud as noise.

    PDFs carry bullets, non-breaking spaces and zero-width marks. A chunk is
    spoken verbatim by Rime, so they have to come out before chunking - not at
    synthesis time, where they would also corrupt the retrieval index.
    """
    text = _UNSPEAKABLE.sub(" ", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return text


def _stem(word: str) -> str:
    """Crude suffix stripping. Enough to match 'opening' to 'open' and
    'refunds' to 'refund', which is where most missed retrievals came from."""
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP]


@dataclass
class Chunk:
    text: str
    source: str
    tokens: Counter


class KnowledgeBase:
    """Loads *.md / *.txt from kb/ and answers questions from them."""

    def __init__(self, directory: Path = KB_DIR):
        self.chunks: list[Chunk] = []
        self.df: Counter = Counter()
        self.skipped: list[tuple[str, str]] = []   # (filename, reason)
        if directory.exists():
            for path in sorted(directory.glob("*")):
                if path.is_dir():
                    continue
                if path.suffix.lower() not in (".md", ".txt", ".pdf"):
                    self.skipped.append((path.name, "unsupported type " + (path.suffix or "none")))
                    continue
                text = clean(read_document(path))
                if not text.strip():
                    self.skipped.append((path.name, "no extractable text - scanned image?"))
                    continue
                for raw in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
                    line = " ".join(raw.split())
                    if len(line) < 20 or line.startswith("#"):
                        continue      # headings are labels, not answers
                    toks = Counter(_tokens(line))
                    if not toks:
                        continue
                    self.chunks.append(Chunk(line, path.name, toks))
                    self.df.update(toks.keys())
        self.n = max(len(self.chunks), 1)
        self._dir = directory
        self._stamp = self._dir_stamp(directory)

    @staticmethod
    def _dir_stamp(directory: Path) -> float:
        """Newest mtime in the kb folder. Cheap change detector so the agent
        process picks up documents added from the web console."""
        if not directory.exists():
            return 0.0
        return max((p.stat().st_mtime for p in directory.glob("*")), default=0.0)

    def maybe_reload(self) -> bool:
        """Re-read the folder if anything changed. Returns True if it did."""
        current = self._dir_stamp(self._dir)
        if current != self._stamp:
            self.__init__(self._dir)
            return True
        return False

    def _score(self, chunk: Chunk, query: list[str]) -> float:
        if not chunk.tokens:
            return 0.0
        total = sum(chunk.tokens.values())
        score = 0.0
        for term in query:
            tf = chunk.tokens.get(term, 0)
            if not tf:
                continue
            idf = math.log((self.n + 1) / (self.df.get(term, 0) + 1)) + 1.0
            score += (tf / total) * idf
        return score / (len(query) ** 0.5 or 1)

    def search(self, question: str) -> list[tuple[float, Chunk]]:
        query = _tokens(question)
        if not query or not self.chunks:
            return []
        ranked = sorted(
            ((self._score(c, query), c) for c in self.chunks),
            key=lambda p: p[0], reverse=True,
        )
        return [(s, c) for s, c in ranked[:TOP_K] if s >= SCORE_FLOOR]

    def answer(self, question: str) -> tuple[str, list[str]]:
        """Return (spoken answer, source lines). Declines rather than guesses."""
        hits = self.search(question)
        if not hits:
            return (
                "I do not have that in our records. I can take a message and "
                "have someone call you back.",
                [],
            )
        spoken = " ".join(c.text for _, c in hits[:2])
        sources = [f"{c.source}: {c.text[:90]}" for _, c in hits]
        return spoken[:400], sources


def add_facts(topic: str, facts: str, directory: Path = KB_DIR) -> str:
    """Append business facts to the knowledge base and return a confirmation.

    Three ways information gets in:
      1. drop a .md or .txt file into kb/  (bulk - the usual way)
      2. the web console's "Add knowledge" box
      3. this function, called by voice for a single correction
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "learned.md"
    body = " ".join(facts.split())
    if not body.endswith("."):
        body += "."
    # Blank line between heading and body: chunks split on blank lines, and a
    # chunk that begins with "#" is treated as a label and skipped.
    entry = "\n\n## " + topic.strip() + "\n\n" + body + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return "Added that to the knowledge base under " + topic.strip() + "."


def _report(kb: KnowledgeBase) -> None:
    """What actually loaded, what was skipped, and whether one file dominates."""
    by_src = Counter(c.source for c in kb.chunks)
    print("knowledge base: %d facts from %d file(s)" % (len(kb.chunks), len(by_src)))
    for name, n in by_src.most_common():
        share = 100.0 * n / max(len(kb.chunks), 1)
        # A single large file is normal. A file that is BOTH dominant and not
        # the smallest source is how unrelated documents hijack retrieval.
        flag = "   <-- largest source" if n == max(by_src.values()) else ""
        print("   %-32s %4d facts  %5.1f%%%s" % (name, n, share, flag))
    for name, reason in kb.skipped:
        print("   SKIPPED %-24s %s" % (name, reason))
    if not kb.chunks:
        print("   nothing loaded. Put .md, .txt or .pdf files in", KB_DIR)


if __name__ == "__main__":
    import sys

    kb = KnowledgeBase()
    _report(kb)

    question = " ".join(a for a in sys.argv[1:] if a != "--list").strip()
    if not question:
        raise SystemExit(0)

    answer, sources = kb.answer(question)
    print()
    print("Q:", question)
    print("A:", answer)
    print("sources:")
    for line in sources:
        print("   -", line)
    if not sources:
        print("   (none - declined rather than guessing)")
