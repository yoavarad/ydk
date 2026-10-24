"""Tests for is_skipped helper."""

import pytest

from ydk.models.verification import CheckResult, is_skipped


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (None, False),
        ({}, False),
        ({"test_count": 2}, False),
        ({"status": "SKIPPED", "skip_reason": "x"}, True),
        ({"skipped": True}, True),
        ({"skipped": False}, False),
    ],
)
def test_is_skipped(detail: dict | None, expected: bool) -> None:
    check = CheckResult(name="c", passed=True, output="", duration_seconds=0.0, detail=detail)
    assert is_skipped(check) is expected


def test_failed_check_never_skipped() -> None:
    check = CheckResult(name="c", passed=False, output="", duration_seconds=0.0, detail={"skipped": True})
    assert is_skipped(check) is False
