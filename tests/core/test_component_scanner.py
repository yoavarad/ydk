"""Tests for the component scanner (Layer B)."""

from __future__ import annotations

import json

from ydk.core.component_scanner import ComponentScanner, LLMProvider
from ydk.models.component import SchemaDefinition, SchemaField


class MockLLMProvider:
    """Mock LLM provider that returns a canned response."""

    def __init__(self, response: str) -> None:
        self._response = response

    def invoke(self, prompt: str) -> str:
        return self._response


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
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("Some content", _make_schemas(), llm_provider=None)
        assert result.unlinked_mentions == []
        assert result.suggested_ids == []

    def test_parses_valid_llm_response(self):
        response = json.dumps(
            {
                "findings": [
                    {
                        "text": "the Order model",
                        "line": 42,
                        "suggested_id": "ydk:entity:orders/Order",
                        "confidence": "HIGH",
                        "reason": "Mentions Order by name",
                    }
                ]
            }
        )
        provider = MockLLMProvider(response)
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("The Order model stores data.", _make_schemas(), llm_provider=provider)

        assert len(result.unlinked_mentions) == 1
        assert result.unlinked_mentions[0].suggested_id == "ydk:entity:orders/Order"
        assert result.unlinked_mentions[0].confidence == "HIGH"
        assert result.suggested_ids == ["ydk:entity:orders/Order"]

    def test_handles_empty_findings(self):
        response = json.dumps({"findings": []})
        provider = MockLLMProvider(response)
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("All properly referenced.", _make_schemas(), llm_provider=provider)
        assert result.unlinked_mentions == []

    def test_handles_malformed_json(self):
        provider = MockLLMProvider("not valid json at all")
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("Content", _make_schemas(), llm_provider=provider)
        assert result.unlinked_mentions == []

    def test_handles_code_fenced_json(self):
        inner = json.dumps(
            {
                "findings": [
                    {
                        "text": "calls Binance",
                        "line": 10,
                        "suggested_id": "ydk:ext:binance/ticker",
                        "confidence": "MEDIUM",
                        "reason": "External dependency mention",
                    }
                ]
            }
        )
        response = f"```json\n{inner}\n```"
        provider = MockLLMProvider(response)
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("calls Binance for prices", _make_schemas(), llm_provider=provider)
        assert len(result.unlinked_mentions) == 1

    def test_multiple_findings(self):
        response = json.dumps(
            {
                "findings": [
                    {
                        "text": "Order model",
                        "line": 5,
                        "suggested_id": "ydk:entity:orders/Order",
                        "confidence": "HIGH",
                        "reason": "Entity mention",
                    },
                    {
                        "text": "create endpoint",
                        "line": 12,
                        "suggested_id": "ydk:route:orders/create",
                        "confidence": "MEDIUM",
                        "reason": "Route mention",
                    },
                ]
            }
        )
        provider = MockLLMProvider(response)
        scanner = ComponentScanner(registry=None)
        result = scanner.scan_narrative("Content", _make_schemas(), llm_provider=provider)
        assert len(result.unlinked_mentions) == 2
        assert len(result.suggested_ids) == 2


class TestBuildPrompt:
    def test_prompt_includes_schema_names(self):
        scanner = ComponentScanner(registry=None)
        prompt = scanner._build_prompt("doc content", _make_schemas())
        assert "entity" in prompt
        assert "route" in prompt
        assert "A domain model" in prompt
        assert "An API endpoint" in prompt

    def test_prompt_includes_narrative(self):
        scanner = ComponentScanner(registry=None)
        prompt = scanner._build_prompt("This is the narrative content to scan.", _make_schemas())
        assert "This is the narrative content to scan." in prompt

    def test_prompt_includes_technical_specs_in_prose_examples(self):
        scanner = ComponentScanner(registry=None)
        prompt = scanner._build_prompt("doc content", _make_schemas())
        assert "field definitions belong in" in prompt
        assert "API shape belongs in" in prompt
        assert "error shape belongs in" in prompt
        assert "Configuration belongs in component manifests" in prompt
        assert "NFRs with adjectives belong in" in prompt


class TestLLMProviderProtocol:
    def test_mock_satisfies_protocol(self):
        provider = MockLLMProvider("response")
        assert isinstance(provider, LLMProvider)
