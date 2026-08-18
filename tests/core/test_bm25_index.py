"""Tests for BM25Index."""

from __future__ import annotations

import json

from ydk.core.bm25_index import BM25Index


class TestBM25IndexAddAndSearch:
    def test_add_and_search_single_document(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "the quick brown fox jumps over the lazy dog")

        results = idx.search("quick fox", n_results=5)
        assert len(results) >= 1
        assert results[0][0] == "doc1"
        assert results[0][1] > 0

    def test_search_ranks_exact_match_higher(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("exact", "kubernetes pod networking configuration")
        idx.add_document("partial", "networking basics for cloud infrastructure")
        idx.add_document("irrelevant", "the quick brown fox jumps over the lazy dog")

        results = idx.search("kubernetes pod networking", n_results=10)
        doc_ids = [r[0] for r in results]
        assert doc_ids[0] == "exact"
        # irrelevant should not appear or be last
        if "irrelevant" in doc_ids:
            assert doc_ids.index("irrelevant") > doc_ids.index("exact")

    def test_search_returns_empty_for_no_match(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "python programming language")

        results = idx.search("xylophone jazz music", n_results=5)
        assert results == []

    def test_search_respects_n_results(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        for i in range(20):
            idx.add_document(f"doc{i}", f"document number {i} about testing search")

        results = idx.search("testing search", n_results=5)
        assert len(results) <= 5

    def test_search_on_empty_index(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        results = idx.search("anything", n_results=5)
        assert results == []


class TestBM25IndexRemove:
    def test_remove_document(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "alpha beta gamma")
        idx.add_document("doc2", "delta epsilon zeta")

        idx.remove_document("doc1")
        results = idx.search("alpha beta", n_results=5)
        doc_ids = [r[0] for r in results]
        assert "doc1" not in doc_ids

    def test_remove_nonexistent_document(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "some content")
        # Should not raise
        idx.remove_document("nonexistent")


class TestBM25IndexPersistence:
    def test_persists_across_instances(self, tmp_path) -> None:
        path = tmp_path / "bm25.json"
        idx1 = BM25Index(index_path=path)
        idx1.add_document("doc1", "persistent search index data")

        # Create new instance from same path
        idx2 = BM25Index(index_path=path)
        results = idx2.search("persistent search", n_results=5)
        assert len(results) >= 1
        assert results[0][0] == "doc1"

    def test_index_file_is_valid_json(self, tmp_path) -> None:
        path = tmp_path / "bm25.json"
        idx = BM25Index(index_path=path)
        idx.add_document("doc1", "hello world")

        data = json.loads(path.read_text())
        assert "documents" in data
        assert "doc1" in data["documents"]


class TestBM25Tokenization:
    def test_removes_stopwords(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "the quick brown fox")

        # Searching for stopwords alone should return nothing
        results = idx.search("the", n_results=5)
        assert results == []

    def test_lowercases_tokens(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "Python Programming Language")

        results = idx.search("python programming", n_results=5)
        assert len(results) >= 1
        assert results[0][0] == "doc1"

    def test_splits_on_punctuation(self, tmp_path) -> None:
        idx = BM25Index(index_path=tmp_path / "bm25.json")
        idx.add_document("doc1", "hello-world, foo.bar; baz!")

        results = idx.search("hello world", n_results=5)
        assert len(results) >= 1
        assert results[0][0] == "doc1"
