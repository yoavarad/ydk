"""Tests for issues 5-8: coverage exclusions, list filters, labels, depends-on validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer

from ydk.cli.task_cmd import _parse_depends_on_arg
from ydk.core.task_validator import check_coverage

# ---------------------------------------------------------------------------
# Issue 5: Coverage exclusions + path matching
# ---------------------------------------------------------------------------


class TestCoverageExclusions:
    def test_excluded_files_not_reported(self) -> None:
        spec_sections = {
            "docs/specs/01-core-domain.md": ["01-core-domain.md"],
            "docs/specs/08-glossary.md": ["08-glossary.md"],
            "docs/specs/09-scope.md": ["09-scope.md"],
        }
        story_refs = {
            "docs/specs/01-core-domain.md": {"S-001"},
        }
        uncovered = check_coverage(
            spec_sections,
            story_refs,
            exclude_patterns=["08-glossary.md", "09-scope.md"],
        )
        assert uncovered == []

    def test_excluded_by_full_path(self) -> None:
        spec_sections = {
            "docs/specs/08-glossary.md": ["08-glossary.md"],
        }
        uncovered = check_coverage(
            spec_sections,
            {},
            exclude_patterns=["docs/specs/08-glossary.md"],
        )
        assert uncovered == []

    def test_no_exclusions_still_reports_uncovered(self) -> None:
        spec_sections = {
            "docs/specs/01-core-domain.md": ["01-core-domain.md"],
            "docs/specs/08-glossary.md": ["08-glossary.md"],
        }
        story_refs = {
            "docs/specs/01-core-domain.md": {"S-001"},
        }
        uncovered = check_coverage(spec_sections, story_refs)
        assert uncovered == ["docs/specs/08-glossary.md"]


class TestCoveragePathMatching:
    def test_basename_matching(self) -> None:
        """Story refs with just filenames should match full-path spec sections."""
        spec_sections = {
            "docs/specs/01-core-domain.md": ["01-core-domain.md"],
        }
        # Story ref uses just the basename
        story_refs = {
            "01-core-domain.md": {"S-001"},
        }
        uncovered = check_coverage(spec_sections, story_refs)
        assert uncovered == []

    def test_full_path_matching(self) -> None:
        """Story refs with full paths should still match."""
        spec_sections = {
            "docs/specs/01-core-domain.md": ["01-core-domain.md"],
        }
        story_refs = {
            "docs/specs/01-core-domain.md": {"S-001"},
        }
        uncovered = check_coverage(spec_sections, story_refs)
        assert uncovered == []

    def test_no_match_still_uncovered(self) -> None:
        spec_sections = {
            "docs/specs/01-core-domain.md": ["01-core-domain.md"],
            "docs/specs/02-api.md": ["02-api.md"],
        }
        story_refs = {
            "01-core-domain.md": {"S-001"},
        }
        uncovered = check_coverage(spec_sections, story_refs)
        assert uncovered == ["docs/specs/02-api.md"]


# ---------------------------------------------------------------------------
# Issue 6: Task list filtering (unit-level — verify CLI args parse)
# ---------------------------------------------------------------------------


class TestListFiltering:
    """Basic verification that the list command accepts --epic and --status."""

    def test_list_command_has_epic_option(self) -> None:
        import inspect

        from ydk.cli.task_cmd import list_tasks

        sig = inspect.signature(list_tasks)
        assert "epic" in sig.parameters
        assert "story" in sig.parameters
        assert "status" in sig.parameters


# ---------------------------------------------------------------------------
# Issue 7: Label creation during init
# ---------------------------------------------------------------------------


class TestLabelCreation:
    def test_required_labels_defined(self) -> None:
        from ydk.cli.init_cmd import _REQUIRED_LABELS

        label_names = [name for name, _color in _REQUIRED_LABELS]
        assert "epic" in label_names
        assert "story" in label_names
        assert "task" in label_names
        assert "blocked-by-code" in label_names
        assert "blocked-by-decision" in label_names
        assert "in-progress" in label_names

    @patch("ydk.cli.init_cmd.subprocess.run")
    def test_create_github_labels_calls_gh(self, mock_run: MagicMock) -> None:
        from ydk.cli.init_cmd import _create_github_labels

        _create_github_labels()
        # Should be called once per label
        from ydk.cli.init_cmd import _REQUIRED_LABELS

        assert mock_run.call_count == len(_REQUIRED_LABELS)
        # Verify the first call uses 'gh label create'
        first_call_args = mock_run.call_args_list[0]
        cmd = first_call_args[0][0]
        assert cmd[0] == "gh"
        assert cmd[1] == "label"
        assert cmd[2] == "create"
        assert "--force" in cmd


# ---------------------------------------------------------------------------
# Issue 8: --depends-on validation
# ---------------------------------------------------------------------------


class TestDependsOnValidation:
    def test_invalid_type_raises_bad_parameter(self) -> None:
        with pytest.raises(typer.BadParameter, match="Invalid dependency type 'nope'"):
            _parse_depends_on_arg(["T-001:nope"])

    def test_valid_types_still_work(self) -> None:
        result = _parse_depends_on_arg(["T-001:validates"])
        assert len(result) == 1

    def test_all_8_types_accepted(self) -> None:
        valid_types = [
            "blocks",
            "validates",
            "caused-by",
            "conditional-blocks",
            "waits-for",
            "discovered-from",
            "supersedes",
            "related",
        ]
        for t in valid_types:
            result = _parse_depends_on_arg([f"T-001:{t}"])
            assert len(result) == 1

    def test_bare_id_still_works(self) -> None:
        result = _parse_depends_on_arg(["T-001"])
        assert result == ["T-001"]


class TestTaskExists:
    def test_local_task_exists(self, tmp_path: pytest.TempPathFactory) -> None:  # type: ignore[type-arg]
        from ydk.repositories.local.tasks import LocalTaskRepository

        repo = LocalTaskRepository(tmp_path)  # type: ignore[arg-type]
        tasks_dir = tmp_path / "tasks"  # type: ignore[operator]
        tasks_dir.mkdir()
        (tasks_dir / "T-001.md").write_text("---\nid: T-001\ntitle: test\n---\nbody")
        assert repo.task_exists("T-001") is True
        assert repo.task_exists("T-999") is False
