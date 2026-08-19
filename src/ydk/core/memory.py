"""ChromaDB-backed memory with local (no-API) embeddings."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from ydk.models.memory import MemoryScore

if TYPE_CHECKING:
    from chromadb import Collection

    from ydk.core.bm25_index import BM25Index

logger = logging.getLogger("ydk.memory")


class MemoryEngine:
    """ChromaDB-backed memory with local (no-API) embeddings."""

    def __init__(
        self,
        chroma_path: str | Path = ".ydk/memory/chroma",
        aws_profile: str = "",
        embedding_model: str = "all-MiniLM-L6-v2",
        aws_region: str = "us-east-1",
    ):
        # aws_profile/aws_region/embedding_model are accepted-but-unused: kept only
        # for backward compat with existing callers (e.g. memory_cmd.py) now that
        # embeddings run locally via ChromaDB's DefaultEmbeddingFunction.
        self._chroma_path = Path(chroma_path)
        self._aws_profile = aws_profile
        self._embedding_model = embedding_model
        self._aws_region = aws_region
        self._client = None  # type: ignore[assignment]
        self._bm25_index_path = self._chroma_path.parent / "bm25_index.json"
        self._bm25: BM25Index | None = None
        self._dim_checked_collections: set[str] = set()

    def _get_client(self):  # noqa: ANN202
        """Lazy init ChromaDB client with local embeddings."""
        if self._client is None:
            try:
                import chromadb
            except ImportError as exc:
                msg = "Install memory support: uv pip install ydk[memory]"
                raise ImportError(msg) from exc
            self._client = chromadb.PersistentClient(path=str(self._chroma_path))
        return self._client

    def _get_embedding_function(self):  # noqa: ANN202
        """Get ChromaDB's local default embedding function (no API, no network calls).

        Runs a MiniLM model locally via onnxruntime -- no AWS/Bedrock dependency.
        ``aws_profile``/``aws_region``/``embedding_model`` are accepted for backward
        config compatibility but are unused by this local function.
        """
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        except ImportError as exc:
            msg = "Install memory support: uv pip install ydk[memory]"
            raise ImportError(msg) from exc

        return DefaultEmbeddingFunction()

    def _get_collection(self, name: str):  # noqa: ANN202
        """Get or create a ChromaDB collection.

        Raises a clear RuntimeError (instead of a raw ChromaDB traceback) if
        the collection already holds embeddings with a different dimensionality
        than the current embedding function -- e.g. leftover 1536-dim vectors
        from the old Bedrock Titan integration colliding with the local
        384-dim MiniLM function.
        """
        client = self._get_client()
        ef = self._get_embedding_function()
        collection = client.get_or_create_collection(name=name, embedding_function=ef)
        self._check_dimension_compat(collection)
        return collection

    def _check_dimension_compat(self, collection: Collection) -> None:
        """Detect a stored-embedding dimension mismatch and fail with a clear message.

        ChromaDB raises InvalidArgumentError the first time a query/add runs
        against a collection whose stored vectors have a different
        dimensionality than the active embedding function. Trigger that check
        once per collection (per engine instance) with a cheap no-op query so
        callers get an actionable message instead of a raw traceback on
        whatever operation happens to run first.
        """
        if collection.name in self._dim_checked_collections:
            return
        self._dim_checked_collections.add(collection.name)

        if collection.count() == 0:
            return

        from chromadb.errors import InvalidArgumentError

        try:
            collection.query(query_texts=[" "], n_results=1)
        except InvalidArgumentError as exc:
            msg = (
                f"Memory collection {collection.name!r} at {self._chroma_path} was indexed "
                "with a different embedding dimensionality than the current embedding "
                "function produces (likely leftover data from the old Bedrock Titan "
                f"embeddings). Delete {self._chroma_path} (or the configured chroma_path) "
                "and re-run `ydk memory index` to rebuild."
            )
            raise RuntimeError(msg) from exc

    def _get_bm25(self) -> BM25Index:
        """Lazy init BM25 index."""
        if self._bm25 is None:
            from ydk.core.bm25_index import BM25Index as _BM25Index

            self._bm25 = _BM25Index(index_path=self._bm25_index_path)
        return self._bm25

    def index_file(self, file_path: Path, collection_name: str) -> int:
        """Index a markdown file into ChromaDB and BM25. Returns number of chunks added.

        Uses hash-based change detection -- skips unchanged files.
        Chunks by H2 headers.
        """
        content = file_path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        collection = self._get_collection(collection_name)

        # Check if already indexed with same hash
        existing = collection.get(where={"$and": [{"source_file": str(file_path)}, {"file_hash": file_hash}]})
        if existing and existing["ids"]:
            return 0  # Already indexed, no changes

        # Delete old chunks for this file
        old = collection.get(where={"source_file": str(file_path)})
        if old and old["ids"]:
            collection.delete(ids=old["ids"])

        # Chunk by H2 headers
        chunks = self._chunk_markdown(content, str(file_path))

        if not chunks:
            return 0

        chunk_ids = [f"{file_path}#{i}" for i in range(len(chunks))]

        # Add chunks to ChromaDB
        collection.add(
            ids=chunk_ids,
            documents=[c["text"] for c in chunks],
            metadatas=[
                {
                    "source_file": str(file_path),
                    "file_hash": file_hash,
                    "section": c["section"],
                    "collection": collection_name,
                    "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                for c in chunks
            ],
        )

        # Also update BM25 index
        bm25 = self._get_bm25()
        for chunk_id, chunk in zip(chunk_ids, chunks, strict=True):
            bm25.add_document(chunk_id, chunk["text"])

        return len(chunks)

    def index_directory(self, directory: Path, collection_name: str, extension: str = ".md") -> dict:
        """Index all files in a directory. Returns {indexed: N, skipped: N, total_chunks: N}."""
        index_start = time.monotonic()
        indexed = 0
        skipped = 0
        total_chunks = 0

        for file_path in sorted(directory.rglob(f"*{extension}")):
            n = self.index_file(file_path, collection_name)
            if n > 0:
                indexed += 1
                total_chunks += n
            else:
                skipped += 1

        elapsed = time.monotonic() - index_start
        logger.info(
            "Indexed %s in %.1fs — %d files, %d chunks, %d skipped",
            directory,
            elapsed,
            indexed,
            total_chunks,
            skipped,
        )
        return {"indexed": indexed, "skipped": skipped, "total_chunks": total_chunks}

    def index_all(self, config=None) -> dict:  # noqa: ANN001
        """Index all configured locations.

        ``config`` can be an YdkConfig object, a dict, or None (uses defaults).
        Returns a summary dict with keys ``files``, ``chunks``, ``skipped``.
        """

        # Normalise config access
        def _get(key: str, default: str) -> str:
            if config is None:
                return default
            if isinstance(config, dict):
                return config.get(key, default)
            # YdkConfig object — try project sub-object first
            proj = getattr(config, "project", config)
            return getattr(proj, key, default)

        locations = {
            "specs": Path(_get("spec_location", "docs/specs")),
            "adrs": Path(_get("adrs_location", "docs/adrs")),
            "research": Path(_get("research_location", "docs/research")),
            "tasks": Path(".ydk/tasks"),
        }

        # Also index project-rules.md as a standalone file
        rules_file = Path("docs/project-rules.md")

        total_files = 0
        total_chunks = 0
        total_skipped = 0

        for name, path in locations.items():
            if path.is_dir():
                r = self.index_directory(path, name)
                total_files += r["indexed"]
                total_chunks += r["total_chunks"]
                total_skipped += r["skipped"]

        if rules_file.is_file():
            n = self.index_file(rules_file, "rules")
            if n > 0:
                total_files += 1
                total_chunks += n
            else:
                total_skipped += 1

        return {"files": total_files, "chunks": total_chunks, "skipped": total_skipped}

    # ------------------------------------------------------------------
    # Hybrid search methods
    # ------------------------------------------------------------------

    def _vector_search(self, query: str, n_results: int = 10, collection_name: str | None = None) -> list[dict]:
        """Run ChromaDB vector similarity search."""
        collections = []
        if collection_name:
            collections = [self._get_collection(collection_name)]
        else:
            self._get_client()  # ensure client is initialized
            for name in ["adrs", "rules", "research", "specs", "tasks", "extractions"]:
                with contextlib.suppress(Exception):
                    collections.append(self._get_collection(name))

        all_results: list[dict] = []
        for col in collections:
            try:
                results = col.query(query_texts=[query], n_results=min(n_results, 5))
                if results and results["documents"]:
                    for i, doc in enumerate(results["documents"][0]):
                        meta = results["metadatas"][0][i] if results["metadatas"] else {}
                        dist = results["distances"][0][i] if results["distances"] else 0
                        all_results.append(
                            {
                                "source": meta.get("source_file", ""),
                                "snippet": doc,
                                "section": meta.get("section", ""),
                                "score": 1 - dist,  # Convert distance to similarity
                                "collection": meta.get("collection", col.name),
                            }
                        )
            except Exception:
                pass

        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results

    def _bm25_search(self, query: str, n_results: int = 10) -> tuple[list[tuple[str, float]], dict[str, dict]]:
        """Run BM25 keyword search. Returns (ranked_results, snippets_map).

        ranked_results: list of (doc_id, score)
        snippets_map: dict mapping doc_id to result metadata dict
        """
        bm25 = self._get_bm25()
        results = bm25.search(query, n_results=n_results)

        snippets: dict[str, dict] = {}
        for doc_id, _score in results:
            # doc_id format: "{file_path}#{chunk_index}" -- parse source info
            parts = doc_id.rsplit("#", 1)
            has_section = len(parts) == 2
            source = parts[0] if has_section else doc_id
            section = parts[1] if has_section else ""
            snippets[doc_id] = {
                "source": source,
                "snippet": "",
                "section": section,
                "collection": "",
            }
        return results, snippets

    def _rrf_fuse(
        self,
        vector_results: list[dict],
        bm25_results: list[tuple[str, float]],
        bm25_snippets: dict[str, dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion: merge vector and BM25 results.

        score = sum(1/(k+rank)) for each result across both lists.
        """
        rrf_scores: dict[str, float] = {}
        result_data: dict[str, dict] = {}

        # Score vector results
        for rank, res in enumerate(vector_results, start=1):
            key = f"{res['source']}#{res['section']}"
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
            result_data[key] = res

        # Score BM25 results
        for rank, (doc_id, _score) in enumerate(bm25_results, start=1):
            meta = bm25_snippets.get(doc_id, {})
            key = f"{meta.get('source', doc_id)}#{meta.get('section', '')}"
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in result_data:
                result_data[key] = {
                    "source": meta.get("source", doc_id),
                    "snippet": meta.get("snippet", ""),
                    "section": meta.get("section", ""),
                    "score": 0.0,
                    "collection": meta.get("collection", ""),
                }

        # Sort by RRF score and attach it
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        fused: list[dict] = []
        for key, score in ranked:
            entry = dict(result_data[key])
            entry["score"] = score
            fused.append(entry)
        return fused

    def search(
        self,
        query: str,
        n_results: int = 10,
        collection_name: str | None = None,
        search_mode: Literal["vector", "keyword", "hybrid"] = "hybrid",
        depth: Literal["index", "summary", "full"] = "full",
        include_expired: bool = False,
    ) -> list[dict]:
        """Search across memories with depth and temporal filtering."""
        search_start = time.monotonic()
        logger.debug("Memory search: mode=%s query=%r", search_mode, query[:80])
        if search_mode == "vector":
            results = self._vector_search(query, n_results=n_results, collection_name=collection_name)
            results = results[:n_results]
        elif search_mode == "keyword":
            bm25_results, bm25_snippets = self._bm25_search(query, n_results=n_results)
            results: list[dict] = []
            for doc_id, score in bm25_results:
                meta = bm25_snippets.get(doc_id, {})
                results.append(
                    {
                        "source": meta.get("source", doc_id),
                        "snippet": meta.get("snippet", ""),
                        "section": meta.get("section", ""),
                        "score": score,
                        "collection": meta.get("collection", ""),
                    }
                )
            results = results[:n_results]
        else:
            # Hybrid mode: run both and fuse with RRF
            vector_results = self._vector_search(query, n_results=n_results, collection_name=collection_name)
            bm25_results, bm25_snippets = self._bm25_search(query, n_results=n_results)
            results = self._rrf_fuse(vector_results, bm25_results, bm25_snippets)[:n_results]

        if not include_expired:
            results = self._filter_expired(results)

        if depth == "index":
            results = self._to_compact_index(results)
        elif depth == "summary":
            for r in results:
                snippet = r.get("snippet", "")
                if len(snippet) > 200:
                    r["snippet"] = snippet[:200] + "..."

        elapsed = time.monotonic() - search_start
        logger.debug("Memory search completed in %.3fs — %d result(s)", elapsed, len(results))
        return results

    def bootstrap(
        self,
        task_description: str,
        spec_refs: list[str],
        n_results: int = 15,
        compact: bool = False,
    ) -> list[dict]:
        """Assemble relevant memories for a task.

        Searches using task description + each spec ref as queries.
        Deduplicates and ranks results.
        """
        all_results: list[dict] = []
        seen_ids: set[str] = set()

        # Search with task description
        for r in self.search(task_description, n_results=5):
            key = f"{r['source']}:{r['section']}"
            if key not in seen_ids:
                seen_ids.add(key)
                all_results.append(r)

        # Search with each spec ref
        for ref in spec_refs:
            for r in self.search(ref, n_results=3):
                key = f"{r['source']}:{r['section']}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_results.append(r)

        all_results.sort(key=lambda x: x["score"], reverse=True)
        results = all_results[:n_results]
        if compact:
            return self._to_compact_index(results)
        return results

    def get_memory_details(self, ids: list[str], collection_name: str = "extractions") -> list[dict]:
        """Retrieve full content for specific memory IDs."""
        collection = self._get_collection(collection_name)
        try:
            result = collection.get(ids=ids)
        except Exception:
            return []
        if not result or not result.get("ids"):
            return []
        details: list[dict] = []
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            doc = result["documents"][i] if result.get("documents") else ""
            details.append(
                {
                    "id": doc_id,
                    "content": doc,
                    "source": meta.get("source_file", ""),
                    "section": meta.get("section", ""),
                    "collection": meta.get("collection", collection_name),
                    "created_at": meta.get("created_at", ""),
                    "source_type": meta.get("source_type", ""),
                    "valid_from": meta.get("valid_from", ""),
                    "valid_until": meta.get("valid_until", ""),
                    **meta,
                }
            )
        return details

    @staticmethod
    def _to_compact_index(results: list[dict]) -> list[dict]:
        """Convert full results to compact index entries."""
        compact: list[dict] = []
        for r in results:
            snippet = r.get("snippet", "")
            preview = snippet[:150] + "..." if len(snippet) > 150 else snippet
            compact.append(
                {
                    "id": f"{r.get('source', '')}#{r.get('section', '')}",
                    "title": r.get("section", "") or r.get("source", ""),
                    "score": r.get("score", 0.0),
                    "snippet_preview": preview,
                }
            )
        return compact

    @staticmethod
    def _filter_expired(results: list[dict]) -> list[dict]:
        """Remove results whose valid_until is set and in the past."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        filtered: list[dict] = []
        for r in results:
            valid_until = r.get("valid_until", "")
            if valid_until and valid_until <= now_iso:
                continue
            filtered.append(r)
        return filtered

    def store(self, memories: list) -> None:
        """Store a list of ExtractedMemory objects into the extractions collection.

        Each memory is expected to have: memory_type, content, related_files, concepts, importance.
        Works with both ExtractedMemory dataclasses and dicts.
        """
        for m in memories:
            if isinstance(m, dict):
                mem_type = m.get("type", m.get("memory_type", "discovery"))
                content = m.get("summary", m.get("content", ""))
                files = m.get("related_files", [])
            else:
                mem_type = getattr(m, "memory_type", "discovery")
                content = getattr(m, "content", "")
                files = getattr(m, "related_files", [])
            if content:
                self.add_extraction(
                    task_id="batch",
                    extraction_type=mem_type,
                    content=content,
                    related_files=files,
                )

    def add_extraction(
        self,
        task_id: str,
        extraction_type: str,
        content: str,
        related_files: list[str] | None = None,
        source_type: str = "llm-extracted",
        verified: bool = False,
        valid_from: str | None = None,
        valid_until: str | None = None,
        contradiction_detector: object | None = None,
        concepts: list[str] | None = None,
    ) -> str:
        """Add an extracted memory to the extractions collection."""
        collection = self._get_collection("extractions")
        now = time.time()
        doc_id = f"extraction-{task_id}-{extraction_type}-{int(now)}"
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        if contradiction_detector is not None:
            self._run_contradiction_check(contradiction_detector, content, concepts or [], collection, now_iso)

        collection.add(
            ids=[doc_id],
            documents=[content],
            metadatas=[
                {
                    "task_id": task_id,
                    "extraction_type": extraction_type,
                    "related_files": ",".join(related_files or []),
                    "extracted_at": now_iso,
                    "collection": "extractions",
                    "category": extraction_type,
                    "source_type": source_type,
                    "verified": verified,
                    "created_at": now_iso,
                    "access_count": 0,
                    "last_accessed": "",
                    "valid_from": valid_from or now_iso,
                    "valid_until": valid_until or "",
                }
            ],
        )
        return doc_id

    def _run_contradiction_check(
        self,
        detector: object,
        content: str,
        concepts: list[str],
        collection: object,
        now_iso: str,
    ) -> None:
        """Run contradiction detection and invalidate contradicted memories."""
        from ydk.core.contradiction_detector import ContradictionDetector
        from ydk.models.memory import ExtractedMemoryModel

        if not isinstance(detector, ContradictionDetector):
            return
        new_mem = ExtractedMemoryModel(memory_type="discovery", content=content, concepts=concepts)
        existing_entries = self._gather_existing_for_contradiction(collection)
        contradictions = detector.check(new_mem, existing_entries)
        for c in contradictions:
            detector.invalidate(c.old_memory_id)
            self._set_valid_until(collection, c.old_memory_id, now_iso)

    @staticmethod
    def _gather_existing_for_contradiction(collection: object) -> list[dict]:
        """Pull existing memories from a ChromaDB collection for contradiction checks."""
        try:
            result = collection.get()  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
        except Exception:
            return []
        if not result or not result.get("ids"):
            return []
        entries: list[dict] = []
        for i, doc_id in enumerate(result["ids"]):
            meta = result["metadatas"][i] if result.get("metadatas") else {}
            doc = result["documents"][i] if result.get("documents") else ""
            if meta.get("valid_until"):
                continue
            concepts_raw = meta.get("concepts", "")
            cl = [c.strip() for c in concepts_raw.split(",") if c.strip()] if concepts_raw else []
            entries.append({"id": doc_id, "content": doc, "concepts": cl})
        return entries

    @staticmethod
    def _set_valid_until(collection: object, memory_id: str, valid_until: str) -> None:
        """Set valid_until metadata on a specific memory."""
        try:
            result = collection.get(ids=[memory_id])  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            if result and result.get("ids"):
                meta = result["metadatas"][0] if result.get("metadatas") else {}
                collection.update(  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
                    ids=[memory_id],
                    metadatas=[{**meta, "valid_until": valid_until}],
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    _PROVENANCE_SCORES: ClassVar[dict[str, float]] = {
        "user-stated": 1.0,
        "verified": 0.9,
        "agent-discovered": 0.7,
        "llm-extracted": 0.5,
    }

    @staticmethod
    def compute_recency(created_epoch: float, now_epoch: float) -> float:
        """Exponential decay with 30-day half-life: ``0.5 ^ (days / 30)``."""
        days = max(0.0, (now_epoch - created_epoch) / 86400.0)
        return 0.5 ** (days / 30.0)

    @staticmethod
    def compute_access_score(access_count: int) -> float:
        """Logarithmic access score: ``log2(count + 1) / 10``, capped at 1.0."""
        return min(1.0, math.log2(access_count + 1) / 10.0)

    def score_results(self, results: list[dict]) -> list[dict]:
        """Apply 4-factor scoring to search results and return sorted by total score."""
        now = time.time()
        scored: list[dict] = []

        for r in results:
            # Parse created_at to epoch
            created_at_str = r.get("created_at", "")
            if created_at_str:
                try:
                    created_epoch = time.mktime(time.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
                except (ValueError, OverflowError):
                    created_epoch = now
            else:
                created_epoch = now

            category = r.get("category", "discovery")
            source_type = r.get("source_type", "llm-extracted")
            access_count = int(r.get("access_count", 0))

            memory_score = MemoryScore(
                category_weight=MemoryScore.category_weight_for(category),
                provenance_score=self._PROVENANCE_SCORES.get(source_type, 0.5),
                recency_score=self.compute_recency(created_epoch, now),
                access_score=self.compute_access_score(access_count),
            )

            scored.append({**r, "memory_score": memory_score})

        scored.sort(key=lambda x: x["memory_score"].total, reverse=True)
        return scored

    def record_access(self, memory_id: str, collection_name: str = "extractions") -> None:
        """Increment access_count and update last_accessed for a memory."""
        collection = self._get_collection(collection_name)
        result = collection.get(ids=[memory_id])
        if not result or not result["ids"]:
            return

        meta = result["metadatas"][0] if result["metadatas"] else {}
        current_count = int(meta.get("access_count", 0))

        collection.update(
            ids=[memory_id],
            metadatas=[
                {
                    **meta,
                    "access_count": current_count + 1,
                    "last_accessed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ],
        )

    @staticmethod
    def _chunk_markdown(content: str, source: str) -> list[dict]:
        """Chunk markdown by H2 headers. Each chunk has text + section name."""
        chunks: list[dict] = []
        current_section = "intro"
        current_text: list[str] = []

        for line in content.splitlines():
            if line.startswith("## "):
                # Save previous chunk
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        chunks.append({"text": text, "section": current_section})
                current_section = line[3:].strip()
                current_text = [line]
            else:
                current_text.append(line)

        # Save last chunk
        if current_text:
            text = "\n".join(current_text).strip()
            if text:
                chunks.append({"text": text, "section": current_section})

        return chunks
