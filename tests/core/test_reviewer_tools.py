"""Tests for inline tools compiled from reviewer YAML files.

Instead of importing tools from a Python module, we load them
from the shipped YAML files to verify the inline code blocks
compile and produce correct results.
"""

from __future__ import annotations

import json

from odk.core.reviewer import load_all_reviewers
from odk.spec_reviewers import REVIEWERS_DIR


def _get_tool(reviewer_id: str, tool_name: str) -> object:
    """Load a specific tool from a reviewer YAML by id and tool name."""
    configs = load_all_reviewers(REVIEWERS_DIR)
    for c in configs:
        if c.id == reviewer_id:
            for t in c.tools:
                if getattr(t, "__name__", "") == tool_name:
                    return t
    msg = f"Tool {tool_name!r} not found in reviewer {reviewer_id!r}"
    raise LookupError(msg)


class TestScanUrlPaths:
    def test_finds_http_methods_with_paths(self) -> None:
        tool = _get_tool("N08", "scan_url_paths")
        text = "The user calls POST /api/v1/orders to place an order."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert len(findings) >= 1
        assert any("POST /api/v1/orders" in f["text"] for f in findings)

    def test_finds_api_paths(self) -> None:
        tool = _get_tool("N08", "scan_url_paths")
        text = "Data is fetched from /api/backtest/results for display."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert len(findings) >= 1
        assert any("/api/backtest/results" in f["text"] for f in findings)

    def test_ignores_odk_references(self) -> None:
        tool = _get_tool("N08", "scan_url_paths")
        text = "The [odk:route:orders/create] endpoint handles order creation."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert all("odk:" not in f["text"] for f in findings)

    def test_empty_text_returns_empty(self) -> None:
        tool = _get_tool("N08", "scan_url_paths")
        findings = json.loads(tool(""))  # type: ignore[operator]
        assert findings == []


class TestScanTypeAnnotations:
    def test_finds_decimal_annotation(self) -> None:
        tool = _get_tool("N08", "scan_type_annotations")
        text = "Price is stored as Decimal(5,4) with default value."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert len(findings) >= 1
        assert any("Decimal(5,4)" in f["text"] for f in findings)

    def test_finds_uuid(self) -> None:
        tool = _get_tool("N08", "scan_type_annotations")
        text = "The order_id is a UUID generated on creation."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert any("UUID" in f["text"] for f in findings)

    def test_finds_list_bracket(self) -> None:
        tool = _get_tool("N08", "scan_type_annotations")
        text = "Returns List[Order] sorted by date."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert any("List[" in f["text"] for f in findings)


class TestScanFillerPhrases:
    def test_finds_filler(self) -> None:
        tool = _get_tool("N07", "scan_filler_phrases")
        text = "It should be noted that in order to process orders, we need a database."
        findings = json.loads(tool(text))  # type: ignore[operator]
        phrases_found = {f["text"] for f in findings}
        assert "it should be noted that" in phrases_found
        assert "in order to" in phrases_found

    def test_clean_text_no_findings(self) -> None:
        tool = _get_tool("N07", "scan_filler_phrases")
        text = "The system processes orders in FIFO sequence."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert len(findings) == 0


class TestScanUnlinkedMentions:
    def test_finds_pascal_case_entities(self) -> None:
        tool = _get_tool("N09", "scan_unlinked_mentions")
        text = "The OrderService processes orders."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert any(f["category"] == "unlinked_entity" for f in findings)

    def test_finds_http_paths(self) -> None:
        tool = _get_tool("N09", "scan_unlinked_mentions")
        text = "Call POST /api/orders to create an order."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert any(f["category"] == "unlinked_route" for f in findings)

    def test_ignores_odk_referenced_terms(self) -> None:
        tool = _get_tool("N09", "scan_unlinked_mentions")
        text = "The [odk:entity:orders/OrderService] processes orders."
        findings = json.loads(tool(text))  # type: ignore[operator]
        assert not any(f["text"] == "OrderService" for f in findings)


class TestAllToolsRegistered:
    """Verify all expected tools are present across YAML files."""

    def test_all_expected_tools_present(self) -> None:
        configs = load_all_reviewers(REVIEWERS_DIR)
        all_tool_names: set[str] = set()
        for c in configs:
            for t in c.tools:
                all_tool_names.add(getattr(t, "__name__", ""))

        expected = {
            "scan_url_paths",
            "scan_type_annotations",
            "scan_filler_phrases",
            "scan_unlinked_mentions",
        }
        assert expected.issubset(all_tool_names)

    def test_all_tools_are_callable(self) -> None:
        configs = load_all_reviewers(REVIEWERS_DIR)
        for c in configs:
            for t in c.tools:
                assert callable(t), f"{c.id} has non-callable tool"
