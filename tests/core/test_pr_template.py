"""Tests for PRBodyBuilder — collapsible PR body with raw verification output."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ydk.core.pr_template import (
    _MAX_BLOCK_CHARS,
    PRBodyBuilder,
    _details_block,
    _extract_review_score,
    _extract_summary_line,
    _truncate_raw,
)


@pytest.fixture
def proof_dir(tmp_path: Path) -> Path:
    d = tmp_path / "proofs" / "T-001"
    d.mkdir(parents=True)
    return d


class TestBuild:
    def test_includes_summary_section(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "## Summary" in body

    def test_includes_agent_summary_when_present(self, proof_dir: Path) -> None:
        (proof_dir / "summary.md").write_text("Implemented the widget feature.")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Implemented the widget feature." in body

    def test_fallback_when_no_summary(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Task T-001" in body

    def test_includes_footer(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Generated with [YDK]" in body

    def test_handles_all_files_missing_gracefully(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "## Summary" in body
        assert "Generated with [YDK]" in body
        assert "## Verification Results" not in body


class TestPluginsSection:
    def test_plugins_rendered_with_pass_status(self, proof_dir: Path) -> None:
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "ruff_check.txt").write_text("PASSED (0.5s)\n\nAll checks passed!")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "### Verification Plugins" in body
        assert "<summary>ruff check — PASS</summary>" in body
        assert "All checks passed!" in body

    def test_plugins_rendered_with_fail_status(self, proof_dir: Path) -> None:
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "pytest.txt").write_text("FAILED (3.0s)\n\n1 failed, 4 passed")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "pytest — FAIL" in body

    def test_multiple_plugins_sorted(self, proof_dir: Path) -> None:
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "aaa_check.txt").write_text("PASSED (0.1s)\n\nok")
        (plugins_dir / "zzz_check.txt").write_text("PASSED (0.2s)\n\nok")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        # Both should appear
        assert "aaa check" in body
        assert "zzz check" in body

    def test_no_plugins_section_when_no_dir(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "### Verification Plugins" not in body

    def test_large_plugin_output_is_truncated(self, proof_dir: Path) -> None:
        """A huge plugin proof file (e.g. verbose pytest output) must not blow
        past GitHub's 65536-char PR body limit -- it should be truncated,
        keeping the tail (most useful for diagnosing failures) and pointing
        to the full proof file."""
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        marker = "END-OF-OUTPUT-MARKER"
        huge = "PASSED (1.0s)\n" + ("line of output\n" * 20000) + marker
        (plugins_dir / "tests-pytest.txt").write_text(huge)

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert len(body) < 10000
        assert "truncated" in body.lower()
        assert ".ydk/proofs/T-001/plugins/tests-pytest.txt" in body
        assert marker in body

    def test_multiple_large_plugins_total_body_under_github_limit(self, proof_dir: Path) -> None:
        """Even with several large plugin outputs, the whole PR body must
        stay under GitHub's 65536-char limit."""
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        for name in ("aaa-check", "bbb-check", "ccc-check"):
            (plugins_dir / f"{name}.txt").write_text("PASSED (1.0s)\n" + ("x" * 50000))

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert len(body) < 65536


class TestReviewsSection:
    def test_reviews_section_rendered(self, proof_dir: Path) -> None:
        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "claude-code-review.txt").write_text("Score: 8/10\nGood implementation.")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "### AI Reviews" in body
        assert "<summary>claude code review — 8/10</summary>" in body

    def test_review_score_na_when_missing(self, proof_dir: Path) -> None:
        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "reviewer-x.txt").write_text("Looks fine, no numeric score given.")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "N/A" in body

    def test_no_reviews_section_when_no_dir(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "### AI Reviews" not in body

    def test_large_review_output_is_truncated(self, proof_dir: Path) -> None:
        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        marker = "END-OF-REVIEW-MARKER"
        huge = "Score: 8/10\n" + ("line of review\n" * 20000) + marker
        (reviews_dir / "claude-review.txt").write_text(huge)

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert len(body) < 10000
        assert "truncated" in body.lower()
        assert ".ydk/proofs/T-001/reviews/claude-review.txt" in body
        assert marker in body


class TestMediaSection:
    def test_screenshots_in_collapsible(self, proof_dir: Path) -> None:
        ss_dir = proof_dir / "screenshots"
        ss_dir.mkdir()
        (ss_dir / "dashboard.png").write_text("fake")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Screenshots (1)" in body
        assert "![dashboard](screenshots/dashboard.png)" in body

    def test_videos_in_collapsible(self, proof_dir: Path) -> None:
        vid_dir = proof_dir / "videos"
        vid_dir.mkdir()
        (vid_dir / "session.webm").write_text("fake")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Videos (1)" in body
        assert "[session.webm](videos/session.webm)" in body

    def test_no_screenshots_section_when_missing(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Screenshots" not in body

    def test_no_videos_section_when_missing(self, proof_dir: Path) -> None:
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "Videos" not in body


class TestTestPlanFromReport:
    def test_test_plan_from_json_report(self, proof_dir: Path) -> None:
        """When verification-report.json exists, test plan is extracted from it."""
        import json

        report_data = {
            "task_id": "T-001",
            "timestamp": "2026-05-06T10:00:00Z",
            "checks": [
                {"name": "ruff/check", "passed": True, "output": "ok", "duration_seconds": 0.5, "detail": None},
                {"name": "pytest", "passed": True, "output": "11 passed", "duration_seconds": 3.0, "detail": None},
            ],
            "all_passed": True,
            "total_duration_seconds": 3.5,
        }
        (proof_dir / "verification-report.json").write_text(json.dumps(report_data))

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "## Test Plan" in body
        assert "2/2 verification checks passed" in body

    def test_test_plan_from_summary(self, proof_dir: Path) -> None:
        """Test plan section in summary.md takes priority."""
        (proof_dir / "summary.md").write_text("## Test Plan\n- Manual smoke test\n- Unit tests pass")
        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)
        assert "## Test Plan" in body
        assert "Manual smoke test" in body


class TestFullTemplate:
    def test_full_template_assembly(self, proof_dir: Path) -> None:
        """End-to-end: all files present, verify full template structure."""
        import json

        (proof_dir / "summary.md").write_text("Added login feature.")

        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "ruff_check.txt").write_text("PASSED (0.5s)\n\nAll checks passed!")
        (plugins_dir / "ruff_format.txt").write_text("PASSED (0.3s)\n\n5 files already formatted")
        (plugins_dir / "ty_check.txt").write_text("PASSED (1.2s)\n\n0 diagnostics")
        (plugins_dir / "pytest.txt").write_text("PASSED (3.1s)\n\n11 passed in 1.2s")

        report_data = {
            "task_id": "T-001",
            "timestamp": "2026-05-06T10:00:00Z",
            "checks": [
                {
                    "name": "ruff/check",
                    "passed": True,
                    "output": "All checks passed!",
                    "duration_seconds": 0.5,
                    "detail": None,
                },
                {"name": "pytest", "passed": True, "output": "11 passed", "duration_seconds": 3.1, "detail": None},
            ],
            "all_passed": True,
            "total_duration_seconds": 5.1,
        }
        (proof_dir / "verification-report.json").write_text(json.dumps(report_data))

        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "claude-review.txt").write_text("Score: 9/10\nExcellent work.")

        ss_dir = proof_dir / "screenshots"
        ss_dir.mkdir()
        (ss_dir / "login-page.png").write_text("fake")

        vid_dir = proof_dir / "videos"
        vid_dir.mkdir()
        (vid_dir / "demo.webm").write_text("fake")

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert "## Summary" in body
        assert "Added login feature." in body
        assert "## Verification Results" in body
        assert "### Verification Plugins" in body
        assert "ruff check" in body
        assert "ruff format" in body
        assert "ty check" in body
        assert "pytest" in body
        assert "### AI Reviews" in body
        assert "claude review — 9/10" in body
        assert "### Screenshots / Videos" in body
        assert "Screenshots (1)" in body
        assert "Videos (1)" in body
        assert "Generated with [YDK]" in body


class TestSummaryExtraction:
    def test_pytest_last_line(self) -> None:
        assert _extract_summary_line("pytest", "collected 5 items\n\n5 passed in 0.3s") == "5 passed in 0.3s"

    def test_ruff_all_passed(self) -> None:
        assert _extract_summary_line("ruff check", "All checks passed!") == "All checks passed!"

    def test_ruff_multi_violations(self) -> None:
        raw = "src/a.py:1:1: E501\nsrc/b.py:2:1: E501\nsrc/c.py:3:1: E501"
        result = _extract_summary_line("ruff check", raw)
        assert "3 issue(s)" in result

    def test_empty_output(self) -> None:
        assert _extract_summary_line("ruff check", "") == "no output"

    def test_ty_error(self) -> None:
        raw = "error[unresolved-attribute]: foo\nerror[unresolved-attribute]: bar"
        result = _extract_summary_line("ty check", raw)
        assert "2 error(s)" in result


class TestDetailsBlockHelper:
    def test_basic_block(self) -> None:
        result = _details_block("my summary", "some content")
        assert "<details>" in result
        assert "<summary>my summary</summary>" in result
        assert "```text\nsome content\n```" in result
        assert "</details>" in result

    def test_empty_content_shows_no_output(self) -> None:
        result = _details_block("empty", "   ")
        assert "(no output)" in result


class TestReviewScoreExtraction:
    def test_score_with_slash(self) -> None:
        assert _extract_review_score("Score: 8/10\nGood work.") == "8/10"

    def test_score_without_slash(self) -> None:
        assert _extract_review_score("score: 7\nOkay.") == "7/10"

    def test_no_score(self) -> None:
        assert _extract_review_score("Looks fine.") == "N/A"


class TestTruncateRawBlockCap:
    def test_truncated_output_never_exceeds_block_cap(self) -> None:
        """The note prepended on truncation must be accounted for in the
        cap, not added on top of a full-length tail."""
        raw = "x" * 100000
        proof_relpath = ".ydk/proofs/T-001/plugins/some-very-long-plugin-file-name.txt"
        result = _truncate_raw(raw, proof_relpath)
        assert len(result) <= _MAX_BLOCK_CHARS

    def test_truncated_output_keeps_tail_marker(self) -> None:
        marker = "END-MARKER"
        raw = ("x" * 10000) + marker
        result = _truncate_raw(raw, ".ydk/proofs/T-001/plugins/p.txt")
        assert marker in result
        assert len(result) <= _MAX_BLOCK_CHARS


class TestSectionBudget:
    def test_many_plugins_stay_under_section_and_body_budget(self, proof_dir: Path) -> None:
        """With a dozen+ plugin proof files, the section (and whole body)
        must stay well under GitHub's 65536-char limit, and an omission
        note must name at least one omitted plugin."""
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        for i in range(20):
            (plugins_dir / f"plugin-{i:02d}.txt").write_text("PASSED (1.0s)\n" + ("x" * 3000))

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert len(body) < 65536
        assert "omitted" in body.lower()
        assert "plugin 19" in body

    def test_few_plugins_all_included_no_omission(self, proof_dir: Path) -> None:
        """With only a few plugins that already fit under the section
        budget, no premature omission should occur (matches prior
        single/triple-large-plugin behavior)."""
        plugins_dir = proof_dir / "plugins"
        plugins_dir.mkdir()
        for name in ("aaa-check", "bbb-check", "ccc-check"):
            (plugins_dir / f"{name}.txt").write_text("PASSED (1.0s)\n" + ("x" * 50000))

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert "omitted" not in body.lower()
        assert "aaa check" in body
        assert "bbb check" in body
        assert "ccc check" in body

    def test_many_reviews_stay_under_section_and_body_budget(self, proof_dir: Path) -> None:
        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        for i in range(20):
            (reviews_dir / f"reviewer-{i:02d}.txt").write_text("Score: 8/10\n" + ("x" * 3000))

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert len(body) < 65536
        assert "omitted" in body.lower()
        assert "reviewer 19" in body

    def test_few_reviews_all_included_no_omission(self, proof_dir: Path) -> None:
        reviews_dir = proof_dir / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "claude-review.txt").write_text("Score: 8/10\nGood implementation.")

        builder = PRBodyBuilder()
        body = builder.build("T-001", proof_dir)

        assert "omitted" not in body.lower()
        assert "claude review" in body
