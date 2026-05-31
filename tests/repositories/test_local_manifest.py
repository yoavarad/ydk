"""Tests for local manifest management."""

import re
import threading
from pathlib import Path

from odk.repositories.local.manifest import Manifest

_HASH_RE = re.compile(r"^[TSE]-[0-9a-f]{8}$")


class TestManifestLoad:
    def test_load_creates_empty_manifest_if_file_missing(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        data = m.load()
        assert data["last_task_id"] == 0
        assert data["last_story_id"] == 0
        assert data["last_epic_id"] == 0
        assert data["tasks"] == {}
        assert data["stories"] == {}
        assert data["epics"] == {}

    def test_load_handles_empty_file(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.yaml").write_text("", encoding="utf-8")
        m = Manifest(tmp_path)
        data = m.load()
        assert data["last_task_id"] == 0

    def test_save_and_load_round_trips(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        data = m.load()
        data["last_task_id"] = 5
        data["tasks"]["T-001"] = {"title": "Test", "status": "open", "story": "S-001", "dependencies": []}
        m.save(data)

        reloaded = m.load()
        assert reloaded["last_task_id"] == 5
        assert reloaded["tasks"]["T-001"]["title"] == "Test"


class TestManifestNextId:
    def test_next_task_id_returns_hash_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        tid = m.next_task_id()
        assert _HASH_RE.match(tid), f"Expected hash ID, got {tid}"

    def test_next_story_id_returns_hash_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        sid = m.next_story_id()
        assert _HASH_RE.match(sid), f"Expected hash ID, got {sid}"

    def test_next_epic_id_returns_hash_format(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        eid = m.next_epic_id()
        assert _HASH_RE.match(eid), f"Expected hash ID, got {eid}"

    def test_ids_are_independent_prefixes(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        tid = m.next_task_id()
        sid = m.next_story_id()
        eid = m.next_epic_id()
        assert tid.startswith("T-")
        assert sid.startswith("S-")
        assert eid.startswith("E-")

    def test_successive_ids_are_unique(self, tmp_path: Path) -> None:
        m = Manifest(tmp_path)
        t1 = m.next_task_id()
        t2 = m.next_task_id()
        assert t1 != t2


class TestManifestConcurrency:
    def test_concurrent_next_ids_no_duplicates(self, tmp_path: Path) -> None:
        """Multiple threads calling next_task_id should produce unique IDs."""
        m = Manifest(tmp_path)
        results: list[str] = []
        lock = threading.Lock()

        def grab_id() -> None:
            tid = m.next_task_id()
            with lock:
                results.append(tid)

        threads = [threading.Thread(target=grab_id) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert len(set(results)) == 20, f"Duplicate IDs: {results}"
