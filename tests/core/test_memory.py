"""Tests for MemoryEngine."""

from __future__ import annotations

import math
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ydk.core.memory import MemoryEngine
from ydk.models.memory import MemoryScore

# ---------------------------------------------------------------------------
# Pure-logic tests (no ChromaDB needed)
# ---------------------------------------------------------------------------


class TestChunkMarkdown:
    """Tests for _chunk_markdown static method."""

    def test_splits_by_h2_headers(self) -> None:
        content = "# Title\nIntro text\n\n## Section A\nContent A\n\n## Section B\nContent B"
        chunks = MemoryEngine._chunk_markdown(content, "test.md")
        assert len(chunks) == 3
        assert chunks[0]["section"] == "intro"
        assert "Intro text" in chunks[0]["text"]
        assert chunks[1]["section"] == "Section A"
        assert "Content A" in chunks[1]["text"]
        assert chunks[2]["section"] == "Section B"
        assert "Content B" in chunks[2]["text"]

    def test_no_headers_single_chunk(self) -> None:
        content = "Just some text\nwith multiple lines\nbut no headers"
        chunks = MemoryEngine._chunk_markdown(content, "test.md")
        assert len(chunks) == 1
        assert chunks[0]["section"] == "intro"
        assert "Just some text" in chunks[0]["text"]

    def test_empty_content(self) -> None:
        chunks = MemoryEngine._chunk_markdown("", "test.md")
        assert chunks == []

    def test_only_whitespace(self) -> None:
        chunks = MemoryEngine._chunk_markdown("   \n\n  ", "test.md")
        assert chunks == []

    def test_h2_header_only(self) -> None:
        content = "## Just a Header"
        chunks = MemoryEngine._chunk_markdown(content, "test.md")
        assert len(chunks) == 1
        assert chunks[0]["section"] == "Just a Header"

    def test_consecutive_h2_headers(self) -> None:
        content = "## First\n## Second\nSome content"
        chunks = MemoryEngine._chunk_markdown(content, "test.md")
        # "## First" alone is a chunk, "## Second\nSome content" is another
        assert len(chunks) == 2
        assert chunks[0]["section"] == "First"
        assert chunks[1]["section"] == "Second"


class TestBootstrapDeduplication:
    """Test that bootstrap deduplicates results from multiple searches."""

    def test_deduplicates_results(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        # Mock search to return overlapping results
        call_count = 0

        def mock_search(query, n_results=10, collection_name=None):
            nonlocal call_count
            call_count += 1
            # All calls return the same item to test deduplication
            return [
                {
                    "text": "shared result",
                    "source": "shared.md",
                    "section": "intro",
                    "score": 0.9,
                    "collection": "test",
                },
                {
                    "text": f"unique-{call_count}",
                    "source": f"unique-{call_count}.md",
                    "section": "intro",
                    "score": 0.8,
                    "collection": "test",
                },
            ]

        engine.search = mock_search  # type: ignore[assignment]

        results = engine.bootstrap("task desc", ["ref1", "ref2"])

        # shared.md:intro should appear only once despite being returned 3 times
        source_keys = [f"{r['source']}:{r['section']}" for r in results]
        assert source_keys.count("shared.md:intro") == 1
        # We should have 4 unique results: shared + unique-1 + unique-2 + unique-3
        assert len(results) == 4


class TestAddExtraction:
    """Test add_extraction stores with correct metadata."""

    def test_stores_with_correct_metadata(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        # Mock _get_collection
        mock_collection = MagicMock()
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        doc_id = engine.add_extraction(
            task_id="T-001",
            extraction_type="discovery",
            content="Found that the auth module uses JWT tokens",
            related_files=["src/auth.py", "src/tokens.py"],
        )

        assert doc_id.startswith("extraction-T-001-discovery-")
        engine._get_collection.assert_called_once_with("extractions")
        mock_collection.add.assert_called_once()

        call_kwargs = mock_collection.add.call_args
        meta = call_kwargs.kwargs["metadatas"][0] if call_kwargs.kwargs else call_kwargs[1]["metadatas"][0]
        assert meta["task_id"] == "T-001"
        assert meta["extraction_type"] == "discovery"
        assert meta["related_files"] == "src/auth.py,src/tokens.py"
        assert meta["collection"] == "extractions"

    def test_stores_provenance_metadata(self) -> None:
        """add_extraction stores source_type and verified in ChromaDB metadata."""
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mock_collection = MagicMock()
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        engine.add_extraction(
            task_id="T-010",
            extraction_type="abandoned",
            content="Tried Redis, rejected due to complexity",
            related_files=["src/cache.py"],
            source_type="llm-extracted",
            verified=False,
        )

        call_kwargs = mock_collection.add.call_args
        meta = call_kwargs.kwargs["metadatas"][0] if call_kwargs.kwargs else call_kwargs[1]["metadatas"][0]
        assert meta["source_type"] == "llm-extracted"
        assert meta["verified"] is False

    def test_stores_verified_provenance(self) -> None:
        """add_extraction stores verified=True when provided."""
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mock_collection = MagicMock()
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        engine.add_extraction(
            task_id="T-011",
            extraction_type="decision",
            content="Chose PostgreSQL for persistence",
            source_type="user-stated",
            verified=True,
        )

        call_kwargs = mock_collection.add.call_args
        meta = call_kwargs.kwargs["metadatas"][0] if call_kwargs.kwargs else call_kwargs[1]["metadatas"][0]
        assert meta["source_type"] == "user-stated"
        assert meta["verified"] is True

    def test_stores_without_related_files(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))
        mock_collection = MagicMock()
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        engine.add_extraction(task_id="T-002", extraction_type="gotcha", content="Watch out for X")

        call_kwargs = mock_collection.add.call_args
        meta = call_kwargs.kwargs["metadatas"][0] if call_kwargs.kwargs else call_kwargs[1]["metadatas"][0]
        assert meta["related_files"] == ""


# ---------------------------------------------------------------------------
# ChromaDB integration tests (use real ChromaDB with default embedding fn)
# ---------------------------------------------------------------------------

try:
    import chromadb.utils.embedding_functions as _ef_module  # noqa: F401

    _skip_chromadb = False
except ModuleNotFoundError:
    _skip_chromadb = True

needs_chromadb = pytest.mark.skipif(_skip_chromadb, reason="chromadb not installed (optional dep)")


@pytest.fixture
def memory_engine(tmp_path):
    """Create a MemoryEngine with mocked Bedrock embedding function.

    Uses ChromaDB's default embedding function instead of Bedrock.
    """
    import chromadb.utils.embedding_functions as ef_module

    engine = MemoryEngine(chroma_path=tmp_path / "chroma")

    # Override _get_embedding_function to use ChromaDB default (no AWS needed)
    default_ef = ef_module.DefaultEmbeddingFunction()
    engine._get_embedding_function = MagicMock(return_value=default_ef)  # type: ignore[assignment]

    return engine


@pytest.fixture
def sample_md_file(tmp_path):
    """Create a sample markdown file."""
    f = tmp_path / "sample.md"
    f.write_text(
        "# Title\nIntro paragraph.\n\n## Section One\nFirst section content.\n\n"
        "## Section Two\nSecond section content.\n"
    )
    return f


@needs_chromadb
class TestIndexFile:
    def test_adds_chunks_to_collection(self, memory_engine, sample_md_file) -> None:
        n = memory_engine.index_file(sample_md_file, "test_col")
        assert n == 3  # intro + Section One + Section Two

    def test_skips_unchanged_files(self, memory_engine, sample_md_file) -> None:
        n1 = memory_engine.index_file(sample_md_file, "test_col")
        assert n1 == 3
        n2 = memory_engine.index_file(sample_md_file, "test_col")
        assert n2 == 0  # Hash match, skip

    def test_reindexes_changed_files(self, memory_engine, sample_md_file) -> None:
        n1 = memory_engine.index_file(sample_md_file, "test_col")
        assert n1 == 3

        # Modify file
        sample_md_file.write_text("# New Title\nNew intro.\n\n## New Section\nNew content.\n")
        n2 = memory_engine.index_file(sample_md_file, "test_col")
        assert n2 == 2  # intro + New Section

        # Verify old chunks are gone -- collection should have exactly 2 docs
        col = memory_engine._get_collection("test_col")
        all_docs = col.get()
        assert len(all_docs["ids"]) == 2


@needs_chromadb
class TestIndexDirectory:
    def test_indexes_multiple_files(self, memory_engine, tmp_path) -> None:
        # Create multiple markdown files
        d = tmp_path / "docs"
        d.mkdir()
        (d / "a.md").write_text("## Alpha\nAlpha content")
        (d / "b.md").write_text("## Beta\nBeta content")
        (d / "c.txt").write_text("Not markdown")

        result = memory_engine.index_directory(d, "docs_col")
        assert result["indexed"] == 2
        assert result["total_chunks"] == 2
        assert result["skipped"] == 0


@needs_chromadb
class TestSearch:
    def test_returns_ranked_results(self, memory_engine, tmp_path) -> None:
        # Index some content
        f = tmp_path / "auth.md"
        f.write_text("## Authentication\nJWT tokens are used for auth.\n\n## Authorization\nRBAC policy engine.\n")
        memory_engine.index_file(f, "docs")

        results = memory_engine.search("JWT authentication", collection_name="docs")
        assert len(results) > 0
        assert results[0]["source"] == str(f)

    def test_search_across_multiple_collections(self, memory_engine, tmp_path) -> None:
        # Index into two different collections
        f1 = tmp_path / "adr.md"
        f1.write_text("## ADR Decision\nWe chose PostgreSQL for persistence.\n")
        memory_engine.index_file(f1, "adrs")

        f2 = tmp_path / "research.md"
        f2.write_text("## Database Research\nPostgreSQL vs MySQL comparison.\n")
        memory_engine.index_file(f2, "research")

        # Search across all (collection_name=None)
        results = memory_engine.search("PostgreSQL database")
        assert len(results) >= 2
        collections_found = {r["collection"] for r in results}
        assert "adrs" in collections_found
        assert "research" in collections_found


# ---------------------------------------------------------------------------
# Memory scoring tests
# ---------------------------------------------------------------------------


class TestMemoryScore:
    """Tests for the MemoryScore model and 4-factor scoring formula."""

    def test_scoring_formula_known_inputs(self) -> None:
        """Verify weighted sum: category*0.50 + provenance*0.15 + recency*0.25 + access*0.10."""
        score = MemoryScore(
            category_weight=0.8,
            provenance_score=1.0,
            recency_score=0.5,
            access_score=0.3,
        )
        expected = 0.8 * 0.50 + 1.0 * 0.15 + 0.5 * 0.25 + 0.3 * 0.10
        assert score.total == pytest.approx(expected)

    def test_all_ones(self) -> None:
        score = MemoryScore(
            category_weight=1.0,
            provenance_score=1.0,
            recency_score=1.0,
            access_score=1.0,
        )
        assert score.total == pytest.approx(1.0)

    def test_all_zeros(self) -> None:
        score = MemoryScore(
            category_weight=0.0,
            provenance_score=0.0,
            recency_score=0.0,
            access_score=0.0,
        )
        assert score.total == pytest.approx(0.0)

    def test_category_weights_all_types(self) -> None:
        """Verify expected category weights for all memory types."""
        expected = {
            "abandoned": 0.9,
            "decision": 0.85,
            "gotcha": 0.8,
            "pattern": 0.7,
            "discovery": 0.6,
            "convention": 0.5,
        }
        for mem_type, weight in expected.items():
            assert MemoryScore.category_weight_for(mem_type) == weight

    def test_category_weight_unknown_defaults(self) -> None:
        """Unknown category types get a default weight."""
        assert MemoryScore.category_weight_for("something_else") == 0.5


class TestDecayFunction:
    """Test the 30-day half-life exponential decay."""

    def test_fresh_memory_scores_one(self) -> None:
        """A memory created right now should have recency ~1.0."""
        now = time.time()
        recency = MemoryEngine.compute_recency(now, now)
        assert recency == pytest.approx(1.0)

    def test_30_day_old_memory_scores_half(self) -> None:
        """A memory created 30 days ago should have recency ~0.5."""
        now = time.time()
        thirty_days_ago = now - 30 * 86400
        recency = MemoryEngine.compute_recency(thirty_days_ago, now)
        assert recency == pytest.approx(0.5, abs=0.01)

    def test_60_day_old_memory_scores_quarter(self) -> None:
        """A memory created 60 days ago should have recency ~0.25."""
        now = time.time()
        sixty_days_ago = now - 60 * 86400
        recency = MemoryEngine.compute_recency(sixty_days_ago, now)
        assert recency == pytest.approx(0.25, abs=0.01)

    def test_fresh_higher_than_old(self) -> None:
        """A fresh memory scores higher than a 60-day-old memory."""
        now = time.time()
        fresh = MemoryEngine.compute_recency(now, now)
        old = MemoryEngine.compute_recency(now - 60 * 86400, now)
        assert fresh > old


class TestAccessScore:
    """Test access_score computation: log2(count+1)/10 capped at 1.0."""

    def test_zero_accesses(self) -> None:
        assert MemoryEngine.compute_access_score(0) == pytest.approx(math.log2(1) / 10)

    def test_one_access(self) -> None:
        assert MemoryEngine.compute_access_score(1) == pytest.approx(math.log2(2) / 10)

    def test_high_count_capped(self) -> None:
        """Very high access counts should be capped at 1.0."""
        assert MemoryEngine.compute_access_score(10000) == 1.0

    def test_monotonically_increasing(self) -> None:
        scores = [MemoryEngine.compute_access_score(i) for i in range(10)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]


class TestScoreResults:
    """Test MemoryEngine.score_results applies 4-factor scoring."""

    def test_scores_and_sorts_results(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 90 * 86400))

        results = [
            {
                "source": "old.md",
                "snippet": "old memory",
                "section": "intro",
                "score": 0.9,
                "collection": "extractions",
                "category": "convention",
                "source_type": "llm-extracted",
                "created_at": old_iso,
                "access_count": 0,
            },
            {
                "source": "new.md",
                "snippet": "new memory",
                "section": "intro",
                "score": 0.8,
                "collection": "extractions",
                "category": "abandoned",
                "source_type": "user-stated",
                "created_at": now_iso,
                "access_count": 5,
            },
        ]

        scored = engine.score_results(results)
        assert len(scored) == 2
        # new memory (abandoned, user-stated, fresh) should rank higher
        assert scored[0]["source"] == "new.md"
        assert scored[1]["source"] == "old.md"
        # Each result should have a memory_score key
        assert "memory_score" in scored[0]
        assert isinstance(scored[0]["memory_score"], MemoryScore)


class TestRecordAccess:
    """Test access counting with mocked collection."""

    def test_increments_access_count(self) -> None:
        engine = MemoryEngine(chroma_path=Path("/tmp/unused"))

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["mem-1"],
            "metadatas": [{"access_count": 3, "last_accessed": ""}],
        }
        engine._get_collection = MagicMock(return_value=mock_collection)  # type: ignore[assignment]

        engine.record_access("mem-1", collection_name="extractions")

        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args
        meta = call_kwargs.kwargs["metadatas"][0] if call_kwargs.kwargs else call_kwargs[1]["metadatas"][0]
        assert meta["access_count"] == 4
        assert "last_accessed" in meta
