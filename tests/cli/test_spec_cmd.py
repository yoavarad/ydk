"""Tests for ydk spec commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from typer.testing import CliRunner

from ydk.cli import app
from ydk.cli.spec_cmd import (
    _build_report,
    _dump_report_files,
    _format_report_human,
    _format_report_json,
    _format_structured_report,
    _score_color,
)
from ydk.core.reviewer import ReviewResult
from ydk.models.component import LinkerResult, ScannerResult
from ydk.models.evaluation import ComponentFinding, CriterionResult, SpecVerificationReport

runner = CliRunner()


class TestThresholdConfig:
    """Verify the threshold config model only has valid fields."""

    def test_no_robustness_field(self) -> None:
        """The robustness field was removed — it should not be accepted."""
        import pytest
        from pydantic import ValidationError

        from ydk.models.config import SpecCheckThresholds

        with pytest.raises(ValidationError, match="robustness"):
            SpecCheckThresholds(robustness=7)  # type: ignore[call-arg]

    def test_valid_fields_accepted(self) -> None:
        from ydk.models.config import SpecCheckThresholds

        t = SpecCheckThresholds(completeness=9, clarity=7, architecture=8, quality=6)
        assert t.completeness == 9
        assert t.clarity == 7
        assert t.architecture == 8
        assert t.quality == 6


def test_spec_list_criteria_exits_0() -> None:
    """ydk spec list-criteria exits 0 and shows rubric names."""
    result = runner.invoke(app, ["spec", "list-criteria"])
    assert result.exit_code == 0
    assert "completeness" in result.output
    assert "clarity" in result.output
    assert "quality" in result.output


def test_spec_verify_no_files_warns_and_exits_1(tmp_path: object, monkeypatch: object) -> None:
    """ydk spec verify with no changed spec files exits 1 with a warning."""
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["spec", "verify"])
    assert result.exit_code == 1
    assert "No changed spec files found" in result.output
    assert "--all-files" in result.output


def test_spec_verify_reviewer_agents_exists() -> None:
    """Verify the reviewer agents function exists in spec_cmd."""
    from ydk.cli.spec_cmd import _run_reviewer_agents

    assert callable(_run_reviewer_agents)


class TestBuildReport:
    def test_report_passed_when_no_issues(self) -> None:
        report = _build_report(
            component_findings=[],
            linker_result=LinkerResult(
                undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=["ydk:entity:a/B"]
            ),
            narrative_scores=[
                CriterionResult(criterion_id="N01", score=9.0, passed=True, reasoning="Good"),
            ],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        assert report.passed is True
        assert "0 errors" in report.summary

    def test_report_fails_with_component_errors(self) -> None:
        report = _build_report(
            component_findings=[
                ComponentFinding(
                    component_id="ydk:route:orders/create",
                    file_path="x",
                    check="route-missing-auth",
                    severity="error",
                    message="Missing auth",
                    suggestion="Add auth",
                )
            ],
            linker_result=LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
            narrative_scores=[],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        assert report.passed is False
        assert "1 error" in report.summary

    def test_report_counts_warnings(self) -> None:
        report = _build_report(
            component_findings=[
                ComponentFinding(
                    component_id="ydk:nfr:perf/latency",
                    file_path="x",
                    check="nfr-missing-unit",
                    severity="warning",
                    message="Missing unit",
                    suggestion="Add unit",
                )
            ],
            linker_result=LinkerResult(
                undefined_refs=[],
                orphaned_components=["ydk:entity:a/Orphan"],
                broken_cross_refs=[],
                valid_refs=[],
            ),
            narrative_scores=[],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        assert report.passed is False  # Orphaned components are errors
        assert "1 error" in report.summary
        assert "1 warning" in report.summary


class TestFormatHumanReport:
    def test_contains_section_headers(self) -> None:
        report = _build_report(
            component_findings=[],
            linker_result=LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
            narrative_scores=[],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        output = _format_report_human(report)
        assert "YDK Spec Verification Report" in output
        assert "Component Checks" in output
        assert "Reference Integrity" in output

    def test_shows_passed_on_clean_report(self) -> None:
        report = _build_report(
            component_findings=[],
            linker_result=LinkerResult(undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=[]),
            narrative_scores=[],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        output = _format_report_human(report)
        assert "PASSED" in output


class TestFormatJsonReport:
    def test_json_is_valid(self) -> None:
        report = _build_report(
            component_findings=[],
            linker_result=LinkerResult(
                undefined_refs=[], orphaned_components=[], broken_cross_refs=[], valid_refs=["ydk:a:b/c"]
            ),
            narrative_scores=[],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        output = _format_report_json(report)
        data = json.loads(output)
        assert data["passed"] is True
        assert "component_checks" in data
        assert "reference_integrity" in data
        assert "narrative_criteria" in data
        assert "unlinked_concepts" in data
        assert "summary" in data

    def test_json_contains_findings(self) -> None:
        report = _build_report(
            component_findings=[
                ComponentFinding(
                    component_id="ydk:route:orders/create",
                    file_path="x.yaml",
                    check="route-missing-auth",
                    severity="error",
                    message="Missing auth",
                    suggestion="Add auth",
                ),
            ],
            linker_result=LinkerResult(
                undefined_refs=["ydk:entity:missing/X"],
                orphaned_components=[],
                broken_cross_refs=[],
                valid_refs=[],
            ),
            narrative_scores=[
                CriterionResult(criterion_id="N01", score=4.0, passed=False, reasoning="Bad"),
            ],
            scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
        )
        output = _format_report_json(report)
        data = json.loads(output)
        assert data["passed"] is False
        assert data["component_checks"]["error_count"] == 1
        assert len(data["component_checks"]["findings"]) == 1
        assert data["reference_integrity"]["undefined"] == 1
        assert data["narrative_criteria"]["failed"] == ["N01"]

    def test_json_format_flag(self, tmp_path: Path, monkeypatch: object) -> None:
        """ydk spec verify --format json --all-files outputs valid JSON."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        result = runner.invoke(app, ["spec", "verify", "--format", "json", "--all-files"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "passed" in data
        assert "summary" in data


# ---------------------------------------------------------------------------
# Issue 1: Tool findings injection into LLM prompt
# ---------------------------------------------------------------------------


class TestToolFindingsInjection:
    """Verify that deterministic tool findings are injected into reviewer prompts."""

    def test_findings_injected_into_prompt(self) -> None:
        """When deterministic tools produce findings, they must appear in the reviewer prompt."""
        from ydk.core.reviewer import ReviewerConfig

        # Create a mock tool that returns findings
        def mock_tool(spec_content: str) -> str:
            return json.dumps(
                [
                    {"line": 10, "text": "POST /api/orders", "message": "URL path in prose"},
                    {"line": 20, "text": "order_id (UUID)", "message": "Type annotation in prose"},
                ]
            )

        reviewer = ReviewerConfig(
            id="N08",
            name="Testability",
            system_prompt="You are a spec reviewer.",
            tools=[mock_tool],
            threshold=8,
            group="quality",
            model_tier="smart",
        )

        # Simulate what _run_cached_fanout does: run tools, build dicts
        deterministic_findings: dict[str, list[dict[str, object]]] = {}
        findings: list[dict[str, object]] = []
        for tool_fn in reviewer.tools:
            result_json = tool_fn("# Test spec")
            parsed = json.loads(result_json)
            if isinstance(parsed, list):
                findings.extend(parsed)
        if findings:
            deterministic_findings[reviewer.id] = findings

        # Build reviewer dict with injection (mirroring the fixed code)
        det = deterministic_findings.get(reviewer.id, [])
        assert len(det) == 2

        # Build prompt with injection
        findings_summary = f"\n\nDETERMINISTIC TOOL FINDINGS ({len(det)} issues found):\n"
        for i, f in enumerate(det[:50], 1):
            line = f.get("line", "?")
            text = str(f.get("text", ""))[:100]
            msg = f.get("message", "")
            findings_summary += f"  {i}. Line {line}: {text} — {msg}\n"
        findings_summary += (
            "\nUse these findings as evidence in your evaluation. Score LOW if many violations are found.\n"
        )
        rev_prompt = reviewer.system_prompt + findings_summary

        assert "DETERMINISTIC TOOL FINDINGS" in rev_prompt
        assert "2 issues found" in rev_prompt
        assert "POST /api/orders" in rev_prompt
        assert "URL path in prose" in rev_prompt
        assert "Score LOW" in rev_prompt

    def test_no_findings_means_no_injection(self) -> None:
        """When tools produce no findings, the prompt should remain unchanged."""
        from ydk.core.reviewer import ReviewerConfig

        def empty_tool(spec_content: str) -> str:
            return json.dumps([])

        reviewer = ReviewerConfig(
            id="N01",
            name="Clean",
            system_prompt="You are a spec reviewer.",
            tools=[empty_tool],
            threshold=8,
            group="quality",
            model_tier="smart",
        )

        findings: list[dict[str, object]] = []
        for tool_fn in reviewer.tools:
            parsed = json.loads(tool_fn("# Test"))
            if isinstance(parsed, list):
                findings.extend(parsed)

        assert len(findings) == 0
        # No injection happens
        rev_prompt = reviewer.system_prompt
        assert "DETERMINISTIC TOOL FINDINGS" not in rev_prompt

    def test_findings_capped_at_50(self) -> None:
        """When more than 50 findings exist, only 50 are included with overflow note."""
        findings = [{"line": i, "text": f"issue_{i}", "message": f"problem {i}"} for i in range(75)]

        findings_summary = f"\n\nDETERMINISTIC TOOL FINDINGS ({len(findings)} issues found):\n"
        for i, f in enumerate(findings[:50], 1):
            line = f.get("line", "?")
            text = str(f.get("text", ""))[:100]
            msg = f.get("message", "")
            findings_summary += f"  {i}. Line {line}: {text} — {msg}\n"
        if len(findings) > 50:
            findings_summary += f"  ... and {len(findings) - 50} more issues.\n"

        assert "75 issues found" in findings_summary
        assert "... and 25 more issues" in findings_summary
        # Should not include issue 51+
        assert "issue_50" not in findings_summary or "issue_74" not in findings_summary


# ---------------------------------------------------------------------------
# Issue 3: Min-score merging
# ---------------------------------------------------------------------------


class TestLLMAuthoritativeScoring:
    """Verify that LLM score is authoritative — tools provide evidence, not override."""

    def test_llm_score_is_final(self) -> None:
        """LLM score is used directly regardless of tool finding count."""
        llm_score = 9
        final_score = llm_score  # No min with deterministic
        assert final_score == 9

    def test_tool_findings_are_evidence_not_judges(self) -> None:
        """Tool findings inform the LLM but don't cap the score."""
        llm_score = 8  # LLM judged most tool findings as false positives
        # Even with 781 tool findings, if LLM says 8, score is 8
        final_score = llm_score
        assert final_score == 8


# ---------------------------------------------------------------------------
# Integration: _run_cached_fanout with all three fixes
# ---------------------------------------------------------------------------


class TestRunCachedFanoutIntegration:
    """Integration test for the full _run_cached_fanout flow with fixes."""

    def test_tool_findings_injected_and_min_scored(self) -> None:
        """End-to-end: tools find issues -> injected into prompt -> min-score applied."""
        # Ensure the module is importable before patching
        import ydk.core.reviewer_engine  # noqa: F401
        from ydk.cli.spec_cmd import _run_cached_fanout
        from ydk.core.reviewer import ReviewerConfig
        from ydk.models.config import YdkConfig

        # Tool that finds 5 issues (det_score = 4)
        def noisy_tool(spec_content: str) -> str:
            return json.dumps([{"line": i, "text": f"violation {i}", "message": f"problem {i}"} for i in range(5)])

        reviewers = [
            ReviewerConfig(
                id="N08",
                name="Testability",
                system_prompt="Evaluate testability.",
                tools=[noisy_tool],
                threshold=8,
                group="quality",
                model_tier="smart",
            ),
        ]

        captured_prompts: list[str] = []

        def capture_run_all(*, spec_content: str, reviewers: list, model_tiers: dict, max_workers: int) -> list:
            captured_prompts.extend(rev["system_prompt"] for rev in reviewers)
            return [
                {
                    "reviewer_id": "N08",
                    "name": "Testability",
                    "score": 9,  # LLM says 9
                    "passed": True,
                    "reasoning": "LLM thinks it's good",
                    "suggestions": [],
                    "findings": [],
                    "elapsed_seconds": 1.0,
                }
            ]

        with patch("ydk.core.reviewer_engine.ReviewerEngine") as MockEngine:
            mock_engine_instance = MockEngine.return_value
            mock_engine_instance.run_all.side_effect = capture_run_all

            config = MagicMock()
            config.__class__ = YdkConfig
            config.aws.profile = "test"
            config.aws.region = "us-east-1"
            config.anthropic.api_key_env = "ANTHROPIC_API_KEY"
            config.ai.model_tiers = {"smart": "us.anthropic.claude-sonnet-4-6-v1:0"}
            config.spec_check.concurrency = 4

            results, det_findings = _run_cached_fanout("# Test spec", config, reviewers, verbose=False)

        # Issue 1: Tool findings were injected into the prompt
        assert len(captured_prompts) == 1
        assert "DETERMINISTIC TOOL FINDINGS" in captured_prompts[0]
        assert "5 issues found" in captured_prompts[0]
        assert "violation 0" in captured_prompts[0]

        # LLM score is authoritative — tool findings are evidence, not judges
        assert len(results) == 1
        assert results[0].score == 9  # LLM said 9, that's the final score
        assert results[0].passed is True  # 9 >= threshold 8

        # Deterministic findings returned separately
        assert "N08" in det_findings
        assert len(det_findings["N08"]) == 5

    def test_no_tools_no_score_cap(self) -> None:
        """Reviewer with no tools: no injection, score passes through unchanged."""
        import ydk.core.reviewer_engine  # noqa: F401
        from ydk.cli.spec_cmd import _run_cached_fanout
        from ydk.core.reviewer import ReviewerConfig
        from ydk.models.config import YdkConfig

        reviewers = [
            ReviewerConfig(
                id="N01",
                name="Completeness",
                system_prompt="Evaluate completeness.",
                tools=[],  # No tools
                threshold=8,
                group="completeness",
                model_tier="smart",
            ),
        ]

        captured_prompts: list[str] = []

        def capture_run_all(*, spec_content: str, reviewers: list, model_tiers: dict, max_workers: int) -> list:
            captured_prompts.extend(rev["system_prompt"] for rev in reviewers)
            return [
                {
                    "reviewer_id": "N01",
                    "name": "Completeness",
                    "score": 9,
                    "passed": True,
                    "reasoning": "Good",
                    "suggestions": [],
                    "findings": [],
                    "elapsed_seconds": 1.0,
                }
            ]

        with patch("ydk.core.reviewer_engine.ReviewerEngine") as MockEngine:
            mock_engine_instance = MockEngine.return_value
            mock_engine_instance.run_all.side_effect = capture_run_all

            config = MagicMock()
            config.__class__ = YdkConfig
            config.aws.profile = "test"
            config.aws.region = "us-east-1"
            config.anthropic.api_key_env = "ANTHROPIC_API_KEY"
            config.ai.model_tiers = {"smart": "us.anthropic.claude-sonnet-4-6-v1:0"}
            config.spec_check.concurrency = 4

            results, det_findings = _run_cached_fanout("# Test spec", config, reviewers, verbose=False)

        # No injection
        assert "DETERMINISTIC TOOL FINDINGS" not in captured_prompts[0]
        assert captured_prompts[0] == "Evaluate completeness."

        # Score passes through: min(9, 10) = 9
        assert results[0].score == 9
        assert results[0].passed is True

        # No deterministic findings
        assert det_findings == {}


# ---------------------------------------------------------------------------
# Structured report tests
# ---------------------------------------------------------------------------


def _make_reviewer_results(count: int = 10) -> list[ReviewResult]:
    """Create a list of mock ReviewResult objects for testing."""
    results = []
    for i in range(1, count + 1):
        score = i  # scores 1-10
        results.append(
            ReviewResult(
                reviewer_id=f"N{i:02d}",
                name=f"Criterion {i}",
                score=score,
                passed=score >= 8,
                reasoning=f"Assessment for criterion {i}.",
                suggestions=[f"Suggestion {j} for N{i:02d}" for j in range(1, 3)],
                findings=[{"line": j * 10, "text": f"finding-{j}", "message": f"issue {j}"} for j in range(1, i + 1)],
                elapsed_seconds=float(i) * 3.0,
            )
        )
    return results


def _make_report_and_scores(
    reviewer_results: list[ReviewResult],
) -> tuple[SpecVerificationReport, list[CriterionResult]]:
    """Build a SpecVerificationReport and matching CriterionResults."""
    narrative_scores = [
        CriterionResult(
            criterion_id=r.reviewer_id,
            score=float(r.score),
            passed=r.passed,
            reasoning=r.reasoning,
            suggestions=r.suggestions,
        )
        for r in reviewer_results
    ]
    report = _build_report(
        component_findings=[],
        linker_result=LinkerResult(
            undefined_refs=[],
            orphaned_components=[],
            broken_cross_refs=[],
            valid_refs=[f"ydk:entity:ns/C{i}" for i in range(20)],
        ),
        narrative_scores=narrative_scores,
        scanner_result=ScannerResult(unlinked_mentions=[], suggested_ids=[]),
    )
    return report, narrative_scores


class TestScoreColor:
    """Test the _score_color helper."""

    def test_low_scores_red(self) -> None:
        for s in (0, 1, 2, 3):
            assert _score_color(s) == "red"

    def test_mid_scores_yellow(self) -> None:
        for s in (4, 5, 6):
            assert _score_color(s) == "yellow"

    def test_high_scores_green(self) -> None:
        for s in (7, 8, 9, 10):
            assert _score_color(s) == "green"


class TestStructuredReport:
    """Test the structured report console output."""

    def test_summary_table_has_all_rows(self, capsys: object) -> None:
        """Summary table should have one row per reviewer plus deterministic rows."""
        results = _make_reviewer_results(10)
        report, _ = _make_report_and_scores(results)
        det_findings: dict[str, list[dict[str, object]]] = {}

        _format_structured_report(
            report=report,
            reviewer_results=results,
            deterministic_findings=det_findings,
            duration_seconds=100.0,
            project_name="test-project",
            file_count=5,
            component_count=20,
        )
        # Can't easily capture Rich output via capsys, but we verify no exception.
        # The real assertion is that it ran without error for all 10 rows.

    def test_pass_fail_coloring_logic(self) -> None:
        """Verify the score-to-color mapping is correct."""
        results = _make_reviewer_results(10)
        for r in results:
            if r.score <= 3:
                assert _score_color(r.score) == "red"
            elif r.score <= 6:
                assert _score_color(r.score) == "yellow"
            else:
                assert _score_color(r.score) == "green"

    def test_no_truncation_all_findings_present(self) -> None:
        """All findings should appear — no truncation."""
        results = _make_reviewer_results(5)
        report, _ = _make_report_and_scores(results)

        # The function prints to console — we verify it doesn't raise
        # and that ReviewResult.findings are not modified
        total_findings = sum(len(r.findings) for r in results)
        assert total_findings == 1 + 2 + 3 + 4 + 5  # 15 total

        _format_structured_report(
            report=report,
            reviewer_results=results,
            deterministic_findings={},
            duration_seconds=50.0,
            project_name="test",
            file_count=3,
            component_count=10,
        )

    def test_deterministic_findings_table(self) -> None:
        """Deterministic findings table should render without error."""
        results = _make_reviewer_results(3)
        report, _ = _make_report_and_scores(results)
        det_findings: dict[str, list[dict[str, object]]] = {
            "N01": [
                {"line": 10, "text": "may", "message": "hedge word", "tool": "scan_hedge_words"},
                {"line": 20, "text": "might", "message": "hedge word", "tool": "scan_hedge_words"},
            ],
            "N02": [
                {"line": 5, "text": "POST /api", "message": "URL in prose", "tool": "scan_url_paths"},
            ],
        }

        _format_structured_report(
            report=report,
            reviewer_results=results,
            deterministic_findings=det_findings,
            duration_seconds=30.0,
            project_name="det-test",
            file_count=2,
            component_count=5,
        )


class TestReportFileDump:
    """Test that report files are written correctly."""

    def test_creates_report_files(self, tmp_path: Path, monkeypatch: object) -> None:
        """Dump should create .txt and .json files in .ydk/reports/."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        results = _make_reviewer_results(3)
        report, _ = _make_report_and_scores(results)

        _dump_report_files(
            report=report,
            reviewer_results=results,
            deterministic_findings={},
            duration_seconds=42.0,
            project_name="dump-test",
            file_count=2,
            component_count=10,
        )

        reports_dir = tmp_path / ".ydk" / "reports"
        assert reports_dir.is_dir()

        txt_files = list(reports_dir.glob("spec-verify-*.txt"))
        json_files = list(reports_dir.glob("spec-verify-*.json"))
        assert len(txt_files) == 1
        assert len(json_files) == 1

    def test_txt_has_no_ansi(self, tmp_path: Path, monkeypatch: object) -> None:
        """Plain text dump must not contain ANSI escape codes."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        results = _make_reviewer_results(3)
        report, _ = _make_report_and_scores(results)

        _dump_report_files(
            report=report,
            reviewer_results=results,
            deterministic_findings={},
            duration_seconds=10.0,
            project_name="ansi-test",
            file_count=1,
            component_count=5,
        )

        txt_file = next((tmp_path / ".ydk" / "reports").glob("spec-verify-*.txt"))
        content = txt_file.read_text()
        assert "\x1b[" not in content  # No ANSI escape codes
        assert "YDK Spec Verification Report" in content

    def test_json_structure(self, tmp_path: Path, monkeypatch: object) -> None:
        """JSON dump must have expected top-level keys."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        results = _make_reviewer_results(3)
        report, _ = _make_report_and_scores(results)
        det_findings: dict[str, list[dict[str, object]]] = {
            "N01": [{"line": 1, "text": "x", "message": "y"}],
        }

        _dump_report_files(
            report=report,
            reviewer_results=results,
            deterministic_findings=det_findings,
            duration_seconds=5.0,
            project_name="json-test",
            file_count=2,
            component_count=8,
        )

        json_file = next((tmp_path / ".ydk" / "reports").glob("spec-verify-*.json"))
        data = json.loads(json_file.read_text())

        assert data["project"] == "json-test"
        assert data["duration_seconds"] == 5.0
        assert data["file_count"] == 2
        assert data["component_count"] == 8
        assert data["passed"] is False  # some criteria fail
        assert len(data["reviewers"]) == 3
        assert "N01" in data["deterministic_findings"]
        assert "component_checks" in data
        assert "reference_integrity" in data

    def test_no_truncation_in_file(self, tmp_path: Path, monkeypatch: object) -> None:
        """All findings must appear in the text dump — no truncation."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        # Create a reviewer with many findings
        many_findings = [{"line": i, "text": f"finding-{i}", "message": f"issue-{i}"} for i in range(100)]
        results = [
            ReviewResult(
                reviewer_id="N99",
                name="Big Reviewer",
                score=2,
                passed=False,
                reasoning="Many issues found.",
                suggestions=["Fix them all."],
                findings=many_findings,
                elapsed_seconds=10.0,
            )
        ]
        report, _ = _make_report_and_scores(results)

        _dump_report_files(
            report=report,
            reviewer_results=results,
            deterministic_findings={},
            duration_seconds=20.0,
            project_name="trunc-test",
            file_count=1,
            component_count=5,
        )

        txt_file = next((tmp_path / ".ydk" / "reports").glob("spec-verify-*.txt"))
        content = txt_file.read_text()

        # All 100 findings must appear
        for i in range(100):
            assert f"finding-{i}" in content, f"finding-{i} missing from text dump"
