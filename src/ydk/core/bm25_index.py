"""BM25 keyword search index with JSON persistence."""

from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Common English stopwords
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
    }
)

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, remove stopwords."""
    tokens = _SPLIT_RE.split(text.lower())
    return [t for t in tokens if t and t not in _STOPWORDS]


class BM25Index:
    """BM25 keyword search index backed by a JSON file.

    Uses standard BM25 formula with k1=1.5, b=0.75.
    """

    def __init__(self, index_path: Path, k1: float = 1.5, b: float = 0.75) -> None:
        self._path = index_path
        self._k1 = k1
        self._b = b

        # Internal state
        self._documents: dict[str, list[str]] = {}  # doc_id -> tokens
        self._doc_lengths: dict[str, int] = {}  # doc_id -> token count
        self._df: dict[str, int] = {}  # term -> document frequency
        self._avg_dl: float = 0.0
        self._n_docs: int = 0

        self._load()

    def _load(self) -> None:
        """Load index from JSON file if it exists."""
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._documents = data.get("documents", {})
        self._doc_lengths = {k: len(v) for k, v in self._documents.items()}
        self._n_docs = len(self._documents)
        self._rebuild_stats()

    def _rebuild_stats(self) -> None:
        """Rebuild df and avgdl from documents."""
        self._df = {}
        total_len = 0
        for tokens in self._documents.values():
            total_len += len(tokens)
            seen: set[str] = set()
            for token in tokens:
                if token not in seen:
                    self._df[token] = self._df.get(token, 0) + 1
                    seen.add(token)
        self._n_docs = len(self._documents)
        self._avg_dl = total_len / self._n_docs if self._n_docs > 0 else 0.0

    def _save(self) -> None:
        """Persist index to JSON."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"documents": self._documents}
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def add_document(self, doc_id: str, text: str) -> None:
        """Tokenize text and add to the index."""
        tokens = _tokenize(text)
        self._documents[doc_id] = tokens
        self._doc_lengths[doc_id] = len(tokens)
        self._rebuild_stats()
        self._save()

    def remove_document(self, doc_id: str) -> None:
        """Remove a document from the index."""
        if doc_id not in self._documents:
            return
        del self._documents[doc_id]
        self._doc_lengths.pop(doc_id, None)
        self._rebuild_stats()
        self._save()

    def search(self, query: str, n_results: int = 10) -> list[tuple[str, float]]:
        """BM25 search. Returns list of (doc_id, score) sorted by score descending."""
        if self._n_docs == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores: dict[str, float] = {}

        for term in query_tokens:
            if term not in self._df:
                continue

            df = self._df[term]
            # IDF component: log((N - df + 0.5) / (df + 0.5) + 1)
            idf = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

            for doc_id, tokens in self._documents.items():
                tf = tokens.count(term)
                if tf == 0:
                    continue
                dl = self._doc_lengths[doc_id]
                # BM25 TF normalization
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * dl / self._avg_dl)
                score = idf * numerator / denominator
                scores[doc_id] = scores.get(doc_id, 0.0) + score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:n_results]
