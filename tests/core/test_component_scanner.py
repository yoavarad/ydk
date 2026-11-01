"""Tests for the component scanner (Layer B)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ydk.core.component_scanner import ComponentScanner
from ydk.core.llm_provider import SubagentHandoff, SubagentProvider
from ydk.models.component import SchemaDefinition, SchemaField

if TYPE_CHECKING:
    from pathlib import Path


class FakeStructuredProvider:
    """Boundary fake: returns a canned validated model and records the call."""

    def __init__(self, findings: list[dict]) -> None:
        self._findings = findings
        self.calls: list[tuple[str, type]] = []

    def invoke(self, prompt: str) -> str:
        return ""

    def invoke_structured(self, prompt, output_format, *, system="", cacheable_context=None):
        self.calls.append((prompt, output_format))
        return output_format.model_validate({"findings": self._findings})


def _make_schemas() -> dict[str, SchemaDefinition]:
    return {
        "entity": SchemaDefinition(
            name="entity",
            description="A domain model / data object",
            version=1,
            fields={
                "id": SchemaField(type="string", required=True, description="Component ID"),
                "description": SchemaField(type="text", required=True, description="What this is"),
            },
        ),
        "route": SchemaDefinition(
            name="route",
            description="An API endpoint",
            version=1,
            fields={
                "id": SchemaField(type="string", required=True, description="Component ID"),
                "method": SchemaField(type="enum", required=True, description="HTTP method", values=["GET", "POST"]),
            },
        ),
    }


class TestScanNarrative:
    def test_returns_empty_when_no_provider(self):
        result = ComponentScanner().scan_narrative("Some content", _make_schemas(), llm_provider=None)
        assert result.unlinked_mentions == []
        assert result.suggested_ids == []

    def test_uses_structured_output(self):
        provider = FakeStructuredProvider(
            [
                {
                    "text": "the Order model",
                    "line": 42,
                    "suggested_id": "ydk:entity:orders/Order",
                    "confidence": "HIGH",
                    "reason": "Mentions Order by name",
                }
            ]
        )
        result = ComponentScanner().scan_narrative("The Order model stores data.", _make_schemas(), provider)

        assert len(result.unlinked_mentions) == 1
        assert result.unlinked_mentions[0].suggested_id == "ydk:entity:orders/Order"
        assert result.suggested_ids == ["ydk:entity:orders/Order"]
        assert "The Order model stores data." in provider.calls[0][0]

    def test_empty_findings(self):
        result = ComponentScanner().scan_narrative("ok", _make_schemas(), FakeStructuredProvider([]))
        assert result.unlinked_mentions == []

    def test_subagent_provider_hands_off_with_layer_b_purpose(self, tmp_path: Path):
        provider = SubagentProvider(
            tmp_path, purpose="layer-b-scan", model_tier="fast", model="m", agent="a", collect=True
        )
        with pytest.raises(SubagentHandoff) as exc:
            ComponentScanner().scan_narrative("Content", _make_schemas(), provider)
        data = json.loads(exc.value.request_paths[0].read_text(encoding="utf-8"))
        assert data["purpose"] == "layer-b-scan"
        assert "Content" in data["user"]

    def test_subagent_response_is_consumed(self, tmp_path: Path):
        provider = SubagentProvider(
            tmp_path, purpose="layer-b-scan", model_tier="fast", model="m", agent="a", collect=True
        )
        with pytest.raises(SubagentHandoff) as exc:
            ComponentScanner().scan_narrative("Content", _make_schemas(), provider)
        req = exc.value.request_paths[0]
        (tmp_path / "responses").mkdir()
        finding = {"text": "t", "line": 1, "suggested_id": "ydk:ext:x/y", "confidence": "HIGH", "reason": "r"}
        (tmp_path / "responses" / req.name).write_text(json.dumps({"findings": [finding]}), encoding="utf-8")

        result = ComponentScanner().scan_narrative("Content", _make_schemas(), provider)

        assert result.suggested_ids == ["ydk:ext:x/y"]


class TestBuildPrompt:
    def test_prompt_includes_schema_names(self):
        scanner = ComponentScanner()
        prompt = scanner._build_prompt("doc content", _make_schemas())
        assert "entity" in prompt
        assert "route" in prompt
        assert "A domain model" in prompt
        assert "An API endpoint" in prompt

    def test_prompt_includes_narrative(self):
        scanner = ComponentScanner()
        prompt = scanner._build_prompt("This is the narrative content to scan.", _make_schemas())
        assert "This is the narrative content to scan." in prompt

    def test_prompt_includes_technical_specs_in_prose_examples(self):
        scanner = ComponentScanner()
        prompt = scanner._build_prompt("doc content", _make_schemas())
        assert "field definitions belong in" in prompt
        assert "API shape belongs in" in prompt
        assert "error shape belongs in" in prompt
        assert "Configuration belongs in component manifests" in prompt
        assert "NFRs with adjectives belong in" in prompt
