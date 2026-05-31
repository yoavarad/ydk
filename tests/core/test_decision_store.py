"""Tests for DecisionStore."""

from __future__ import annotations

from odk.core.decision_store import DecisionStore
from odk.models.decision import Decision


class TestDecisionRecord:
    def test_record_creates_first_version(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "decisions")
        d = store.record("database", "Use PostgreSQL", "Best DB")
        assert isinstance(d, Decision)
        assert d.version == 1
        assert d.supersedes is None

    def test_record_auto_increments(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "decisions")
        d1 = store.record("db", "PostgreSQL", "v1")
        d2 = store.record("db", "SQLite", "v2")
        assert d1.version == 1
        assert d2.version == 2

    def test_record_sets_supersedes(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "decisions")
        store.record("db", "PostgreSQL", "v1")
        d2 = store.record("db", "SQLite", "v2")
        assert d2.supersedes == "v1"

    def test_creates_yaml_file(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "decisions")
        store.record("api-format", "REST", "std")
        assert (tmp_path / "decisions" / "api-format.yaml").is_file()


class TestDecisionGetCurrent:
    def test_returns_latest(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "d")
        store.record("db", "PG", "v1")
        store.record("db", "SQLite", "v2")
        store.record("db", "DuckDB", "v3")
        c = store.get_current("db")
        assert c is not None
        assert c.content == "DuckDB"
        assert c.version == 3

    def test_returns_none_for_unknown(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "d")
        assert store.get_current("x") is None


class TestDecisionGetHistory:
    def test_newest_first(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "d")
        store.record("db", "PG", "v1")
        store.record("db", "SQLite", "v2")
        store.record("db", "DuckDB", "v3")
        h = store.get_history("db")
        assert len(h) == 3
        assert h[0].version == 3
        assert h[2].version == 1

    def test_empty_for_unknown(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "d")
        assert store.get_history("x") == []


class TestDecisionListTopics:
    def test_returns_all(self, tmp_path) -> None:
        store = DecisionStore(base_path=tmp_path / "d")
        store.record("database", "PG", "r1")
        store.record("cache", "Redis", "r1")
        assert set(store.list_topics()) == {"database", "cache"}

    def test_empty(self, tmp_path) -> None:
        assert DecisionStore(base_path=tmp_path / "d").list_topics() == []


class TestDecisionPersistence:
    def test_survives_reload(self, tmp_path) -> None:
        p = tmp_path / "d"
        DecisionStore(base_path=p).record("db", "PG", "v1")
        DecisionStore(base_path=p).record("db", "SQLite", "v2")
        c = DecisionStore(base_path=p).get_current("db")
        assert c is not None
        assert c.content == "SQLite"
        assert c.version == 2
