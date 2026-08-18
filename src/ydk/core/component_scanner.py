"""Layer B LLM prose scanner — detects unlinked component references in narratives."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ydk.models.component import ScannerFinding, ScannerResult

if TYPE_CHECKING:
    from ydk.models.component import SchemaDefinition


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used by the scanner."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


def _build_scanner_prompt_template() -> str:
    """Build the LLM prompt template as a list of lines to avoid E501."""
    lines = [
        "You are a specification reference auditor for the YDK component manifest system.",
        "",
        "In this system, every structured concept in a specification MUST be referenced",
        "by its full component ID in square brackets, like [ydk:entity:orders/Order]",
        "or [ydk:route:orders/create].",
        "",
        "Your job: Read the narrative document below and identify ANY concept that is",
        "mentioned in prose without a proper [ydk:...] reference.",
        "",
        "STEP 1: Read the schema definitions provided below. Each schema file defines a",
        "component type that exists in this project. The schema's `name` field is the type,",
        "and its `description` field tells you what kind of concept it represents. Use these",
        "schemas to understand the full set of component types - do NOT assume a fixed list.",
        "",
        "--- SCHEMA DEFINITIONS ---",
        "{schema_definitions}",
        "",
        "STEP 2: For each component type defined in the schemas, scan the narrative for",
        "prose mentions of that kind of concept without a proper [ydk:...] reference.",
        "",
        "Here are examples of the kinds of things to catch (these are illustrative, not",
        "exhaustive - use the schema definitions above as the authoritative list):",
        "",
        'Data models / domain objects (commonly type "entity"):',
        '- BAD: "the Order model stores..." -> should be [ydk:entity:orders/Order]',
        '- BAD: "creates a new User record" -> should be [ydk:entity:users/User]',
        "",
        'API endpoints (commonly type "route"):',
        '- BAD: "POST to create an order" -> should be [ydk:route:orders/create]',
        '- BAD: "calls the login endpoint" -> should be [ydk:route:auth/login]',
        "",
        'Error responses (commonly type "error"):',
        '- BAD: "returns insufficient balance error"',
        "  -> should be [ydk:error:orders/insufficient-balance]",
        "",
        'Business rules (commonly type "req"):',
        '- BAD: "the system validates the balance"',
        "  -> should be [ydk:req:orders/validate-balance]",
        "",
        'External dependencies (commonly type "ext"):',
        '- BAD: "calls Binance for the price" -> should be [ydk:ext:binance/ticker]',
        "",
        "Cross-cutting concerns, events, hooks, NFRs, tests, pages, UI components,",
        "contracts - and ANY other type defined in the schemas above.",
        "",
        "Technical specifications in prose (should be components):",
        '- BAD: "Order has fields: order_id (UUID), symbol (str), quantity (Decimal)"',
        "  -> These field definitions belong in [ydk:entity:orders/Order] manifest, not prose",
        '- BAD: "POST /api/v1/orders expects {{ symbol: string, side: enum }}"',
        "  -> This API shape belongs in [ydk:route:orders/create] manifest",
        "- BAD: \"Returns 422 with {{ type: 'insufficient_balance' }}\"",
        "  -> This error shape belongs in [ydk:error:orders/insufficient-balance] manifest",
        '- BAD: "The config has DATABASE_URL, REDIS_HOST, API_KEY settings"',
        "  -> Configuration belongs in component manifests, not narrative prose",
        '- BAD: "response latency should be fast"',
        "  -> NFRs with adjectives belong in [ydk:nfr:...] with numeric targets",
        "",
        "For each finding, output:",
        "1. The exact text from the document that mentions the concept without a reference",
        "2. The line number (approximate is fine)",
        "3. The suggested component ID it should reference",
        "4. Confidence: HIGH (clearly a specific concept), MEDIUM (likely), LOW (general)",
        "",
        "Only report HIGH and MEDIUM confidence findings. Ignore generic programming terms,",
        "general descriptions, and conceptual language that does not refer to a specific",
        "project component.",
        "",
        "Do NOT report text that is already inside [ydk:...] brackets.",
        "",
        "Return JSON:",
        "{{",
        '  "findings": [',
        "    {{",
        '      "text": "the quoted text from the document",',
        '      "line": 42,',
        '      "suggested_id": "ydk:entity:orders/Order",',
        '      "confidence": "HIGH",',
        '      "reason": "Mentions Order model by name without reference"',
        "    }}",
        "  ]",
        "}}",
        "",
        "--- DOCUMENT ---",
        "{narrative_content}",
    ]
    return "\n".join(lines)


_SCANNER_PROMPT_TEMPLATE = _build_scanner_prompt_template()


class ComponentScanner:
    """LLM-based prose scanner (Layer B).

    Scans narrative documents for concepts mentioned without proper
    [ydk:...] references by sending content to an LLM with a
    schema-driven prompt.
    """

    def __init__(self, registry: object) -> None:
        self._registry = registry

    def scan_narrative(
        self,
        content: str,
        schemas: dict[str, SchemaDefinition],
        llm_provider: LLMProvider | None = None,
    ) -> ScannerResult:
        """Scan a narrative document for unlinked component mentions.

        If no LLM provider is given, returns an empty result (graceful skip).
        """
        if llm_provider is None:
            return ScannerResult(unlinked_mentions=[], suggested_ids=[])

        prompt = self._build_prompt(content, schemas)
        response = llm_provider.invoke(prompt)
        return self._parse_response(response)

    def _build_prompt(self, content: str, schemas: dict[str, SchemaDefinition]) -> str:
        """Build the LLM prompt dynamically from loaded schemas."""
        schema_lines: list[str] = []
        for schema in sorted(schemas.values(), key=lambda s: s.name):
            schema_lines.append(f"Type: {schema.name}")
            schema_lines.append(f"  Description: {schema.description}")
            field_names = ", ".join(schema.fields.keys())
            schema_lines.append(f"  Fields: {field_names}")
            schema_lines.append("")

        schema_definitions = "\n".join(schema_lines)
        return _SCANNER_PROMPT_TEMPLATE.format(
            schema_definitions=schema_definitions,
            narrative_content=content,
        )

    def _parse_response(self, response: str) -> ScannerResult:
        """Parse the LLM JSON response into a ScannerResult."""
        try:
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)

            data = json.loads(text)
            findings_data = data.get("findings", [])
            findings: list[ScannerFinding] = []
            suggested_ids: list[str] = []
            for f in findings_data:
                finding = ScannerFinding(
                    text=f.get("text", ""),
                    line=f.get("line", 0),
                    suggested_id=f.get("suggested_id", ""),
                    confidence=f.get("confidence", "LOW"),
                    reason=f.get("reason", ""),
                )
                findings.append(finding)
                if finding.suggested_id:
                    suggested_ids.append(finding.suggested_id)

            return ScannerResult(unlinked_mentions=findings, suggested_ids=suggested_ids)
        except (json.JSONDecodeError, KeyError, TypeError):
            return ScannerResult(unlinked_mentions=[], suggested_ids=[])
