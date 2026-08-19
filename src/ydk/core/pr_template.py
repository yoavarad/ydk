"""Deterministic PR body builder — assembles PR body from proof files.

The template is a string constant.  The agent does not influence the
proof sections; only ``summary.md`` is agent-authored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class PRBodyBuilder:
    """Build a deterministic PR body from proof artifacts on disk."""

    def build(self, task_id: str, proof_dir: Path) -> str:
        """Assemble the full PR body from files in *proof_dir*.

        Reads each proof file if it exists; gracefully omits sections
        whose files are missing.  Each verification result is wrapped
        in a collapsible ``<details>`` block with raw terminal output.
        """
        parts: list[str] = []

        # --- Summary (agent-authored) ---
        parts.append("## Summary\n")
        summary_path = proof_dir / "summary.md"
        if summary_path.exists():
            parts.append(summary_path.read_text().strip())
            parts.append("")
        else:
            parts.append(f"Task {task_id}")
            parts.append("")

        # --- Verification Results ---
        plugin_section = self._plugins_section(proof_dir)
        review_section = self._reviews_section(proof_dir)
        media_section = self._media_section(proof_dir)

        has_any_verification = bool(plugin_section or review_section or media_section)

        if has_any_verification:
            parts.append("## Verification Results\n")

        if plugin_section:
            parts.append("### Verification Plugins\n")
            parts.append(plugin_section)

        if review_section:
            parts.append("### AI Reviews\n")
            parts.append(review_section)

        if media_section:
            parts.append(media_section)

        # --- Test Plan ---
        test_plan = self._extract_test_plan(proof_dir)
        if test_plan:
            parts.append("## Test Plan\n")
            parts.append(test_plan)
            parts.append("")

        # --- Footer ---
        parts.append("\U0001f916 Generated with [YDK](https://github.com/oaltagar-personal/ydk)")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _plugins_section(self, proof_dir: Path) -> str:
        """Build collapsible blocks for each plugin output file."""
        plugins_dir = proof_dir / "plugins"
        if not plugins_dir.is_dir():
            return ""
        blocks: list[str] = []
        for plugin_file in sorted(plugins_dir.glob("*.txt")):
            raw = plugin_file.read_text()
            plugin_name = plugin_file.stem.replace("-", " ").replace("_", " ")
            status = "PASS" if raw.startswith("PASSED") else "FAIL"
            summary_text = f"{plugin_name} — {status}"
            blocks.append(_details_block(summary_text, raw))
        return "\n".join(blocks) if blocks else ""

    def _reviews_section(self, proof_dir: Path) -> str:
        """Build collapsible blocks for each AI review output file."""
        reviews_dir = proof_dir / "reviews"
        if not reviews_dir.is_dir():
            return ""
        blocks: list[str] = []
        for review_file in sorted(reviews_dir.glob("*.txt")):
            raw = review_file.read_text()
            reviewer_name = review_file.stem.replace("-", " ").replace("_", " ")
            score = _extract_review_score(raw)
            summary_text = f"{reviewer_name} — {score}"
            blocks.append(_details_block(summary_text, raw))
        return "\n".join(blocks) if blocks else ""

    def _media_section(self, proof_dir: Path) -> str:
        """Build screenshots and videos sections."""
        parts: list[str] = []

        screenshots = self._list_images(proof_dir)
        if screenshots:
            lines = ["<details>", f"<summary>Screenshots ({len(screenshots)})</summary>", ""]
            for img in screenshots:
                label = img.stem.replace("-", " ").replace("_", " ")
                lines.append(f"![{label}](screenshots/{img.name})")
                lines.append("")
            lines.append("</details>")
            parts.append("\n".join(lines))

        videos_dir = proof_dir / "videos"
        videos = self._list_videos(videos_dir) if videos_dir.is_dir() else []
        # Also check root-level videos for backward compat
        root_videos = self._list_videos(proof_dir)
        all_videos = videos + root_videos
        if all_videos:
            lines = ["<details>", f"<summary>Videos ({len(all_videos)})</summary>", ""]
            for vid in all_videos:
                if vid.parent.name == "videos":
                    lines.append(f"[{vid.name}](videos/{vid.name})")
                else:
                    lines.append(f"[{vid.name}]({vid.name})")
                lines.append("")
            lines.append("</details>")
            parts.append("\n".join(lines))

        # Wrap in a subsection header if we have media
        if parts:
            return "### Screenshots / Videos\n\n" + "\n\n".join(parts) + "\n"
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_test_plan(self, proof_dir: Path) -> str:
        """Extract test plan from summary.md or pytest output."""
        summary_path = proof_dir / "summary.md"
        if summary_path.exists():
            content = summary_path.read_text()
            # Look for a "## Test Plan" section in the summary
            for marker in ("## Test Plan", "### Test Plan", "**Test Plan**"):
                if marker in content:
                    idx = content.index(marker)
                    plan = content[idx + len(marker) :].strip()
                    # Take until next heading or end
                    lines: list[str] = []
                    for line in plan.splitlines():
                        if line.startswith("## ") and lines:
                            break
                        lines.append(line)
                    return "\n".join(lines).strip()

        # Fallback: extract from verification report JSON
        report_path = proof_dir / "verification-report.json"
        if report_path.exists():
            from ydk.models.verification import VerificationReport

            report = VerificationReport.model_validate_json(report_path.read_text())
            passed = sum(1 for c in report.checks if c.passed)
            total = len(report.checks)
            return f"- {passed}/{total} verification checks passed ({report.total_duration_seconds:.1f}s)"
        return ""

    @staticmethod
    def _list_images(proof_dir: Path) -> list[Path]:
        screenshots_dir = proof_dir / "screenshots"
        if not screenshots_dir.is_dir():
            return []
        extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        return sorted(p for p in screenshots_dir.iterdir() if p.suffix.lower() in extensions)

    @staticmethod
    def _list_videos(directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        extensions = {".webm", ".mp4", ".avi", ".mov"}
        return sorted(p for p in directory.iterdir() if p.suffix.lower() in extensions)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _details_block(summary: str, raw_content: str) -> str:
    """Build a single ``<details>`` block with raw content in a code fence."""
    content = raw_content.strip() if raw_content.strip() else "(no output)"
    return f"<details>\n<summary>{summary}</summary>\n\n```text\n{content}\n```\n\n</details>\n"


def _extract_summary_line(label: str, raw: str) -> str:
    """Extract a one-line pass/fail summary from raw tool output."""
    stripped = raw.strip()
    if not stripped:
        return "no output"

    if label == "pytest":
        # Last line of pytest output usually has "X passed" or "X failed"
        last = stripped.splitlines()[-1].strip()
        return last if last else "no output"

    if label in ("ruff check", "ruff format"):
        if "all checks passed" in stripped.lower():
            return "All checks passed!"
        if not stripped or stripped.isspace():
            return "clean"
        # Count lines as proxy for violation count
        line_count = len(stripped.splitlines())
        if line_count == 1:
            return stripped.splitlines()[0]
        return f"{line_count} issue(s) found"

    if label == "ty check":
        if not stripped:
            return "clean"
        if "error" in stripped.lower():
            line_count = len([ln for ln in stripped.splitlines() if "error" in ln.lower()])
            return f"{line_count} error(s)" if line_count else stripped.splitlines()[0]
        return stripped.splitlines()[0]

    # Generic fallback: first line
    return stripped.splitlines()[0]


def _extract_review_score(raw: str) -> str:
    """Extract score from AI review output."""
    import re

    # Look for patterns like "Score: 8/10", "8/10", "score: 8"
    match = re.search(r"(?:score[:\s]*)?(\d{1,2})\s*/\s*10", raw, re.IGNORECASE)
    if match:
        return f"{match.group(1)}/10"
    match = re.search(r"score[:\s]*(\d{1,2})", raw, re.IGNORECASE)
    if match:
        return f"{match.group(1)}/10"
    return "N/A"
