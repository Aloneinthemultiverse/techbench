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


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


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
        if directory.exists():
            for path in sorted(directory.glob("*")):
                if path.suffix.lower() not in (".md", ".txt"):
                    continue
                for raw in re.split(r"(?<=[.!?])\s+|\n{2,}", path.read_text(encoding="utf-8")):
                    line = " ".join(raw.split())
                    if len(line) < 20 or line.startswith("#"):
                        continue      # headings are labels, not answers
                    toks = Counter(_tokens(line))
                    if not toks:
                        continue
                    self.chunks.append(Chunk(line, path.name, toks))
                    self.df.update(toks.keys())
        self.n = max(len(self.chunks), 1)

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


if __name__ == "__main__":
    import sys
    kb = KnowledgeBase()
    print("chunks loaded:", len(kb.chunks))
    q = " ".join(sys.argv[1:]) or "what are your opening hours"
    answer, sources = kb.answer(q)
    print("\nQ:", q)
    print("A:", answer)
    print("\nsources:")
    for s in sources:
        print("  -", s)
