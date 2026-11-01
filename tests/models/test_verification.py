"""Tests for ydk.models.verification status helpers."""

from __future__ import annotations

from typing import Any

from ydk.models.verification import NEEDS_LLM, CheckResult, is_needs_llm, is_skipped, needs_llm_requests


def _check(name: str = "c", *, passed: bool = False, detail: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, passed=passed, output="", duration_seconds=0.0, detail=detail)


def test_is_needs_llm_true_for_needs_llm_status() -> None:
    assert is_needs_llm(_check(detail={"status": NEEDS_LLM, "request_paths": ["a.json"]}))


def test_is_needs_llm_false_otherwise() -> None:
    assert not is_needs_llm(_check())
    assert not is_needs_llm(_check(passed=True, detail={"status": "SKIPPED"}))


def test_needs_llm_check_is_not_skipped() -> None:
    assert not is_skipped(_check(detail={"status": NEEDS_LLM, "request_paths": []}))


def test_needs_llm_requests_collects_paths_in_order_once() -> None:
    checks = [
        _check("a", detail={"status": NEEDS_LLM, "request_paths": ["r1.json", "r2.json"]}),
        _check("b", passed=True),
        _check("c", detail={"status": NEEDS_LLM, "request_paths": ["r2.json", "r3.json"]}),
    ]

    assert needs_llm_requests(checks) == ["r1.json", "r2.json", "r3.json"]


def test_needs_llm_requests_empty_without_needs_llm_checks() -> None:
    assert needs_llm_requests([_check(passed=True), _check()]) == []
