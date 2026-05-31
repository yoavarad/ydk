"""Append-only decision store backed by per-topic YAML files."""

from __future__ import annotations

import time
from pathlib import Path

import yaml

from odk.models.decision import Decision


class DecisionStore:
    """Manage versioned decisions stored as YAML files."""

    def __init__(self, base_path: str | Path = ".odk/memory/decisions") -> None:
        self._base = Path(base_path)

    def _topic_path(self, topic: str) -> Path:
        """Return the YAML file path for a given topic."""
        safe_name = topic.replace(" ", "-").replace("/", "_").lower()
        return self._base / f"{safe_name}.yaml"

    def _load_versions(self, topic: str) -> list[dict]:
        """Load all versions for a topic from its YAML file."""
        path = self._topic_path(topic)
        if not path.is_file():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data

    def _save_versions(self, topic: str, versions: list[dict]) -> None:
        """Persist all versions for a topic to its YAML file."""
        path = self._topic_path(topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(versions, default_flow_style=False, sort_keys=False), encoding="utf-8")

    def record(self, topic: str, content: str, rationale: str) -> Decision:
        """Append a new version of a decision for *topic*."""
        versions = self._load_versions(topic)
        next_version = len(versions) + 1
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        supersedes: str | None = None
        if versions:
            prev = versions[-1]
            supersedes = f"v{prev['version']}"

        decision = Decision(
            topic=topic,
            content=content,
            rationale=rationale,
            version=next_version,
            created_at=now_iso,
            supersedes=supersedes,
        )
        versions.append(decision.model_dump())
        self._save_versions(topic, versions)
        return decision

    def get_current(self, topic: str) -> Decision | None:
        """Return the latest version for *topic*, or None."""
        versions = self._load_versions(topic)
        if not versions:
            return None
        return Decision(**versions[-1])

    def get_history(self, topic: str) -> list[Decision]:
        """Return all versions for *topic*, newest first."""
        versions = self._load_versions(topic)
        return [Decision(**v) for v in reversed(versions)]

    def list_topics(self) -> list[str]:
        """Return all known decision topics."""
        if not self._base.is_dir():
            return []
        topics: list[str] = []
        for path in sorted(self._base.glob("*.yaml")):
            versions = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(versions, list) and versions:
                topics.append(versions[0]["topic"])
        return topics
