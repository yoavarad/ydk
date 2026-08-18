"""Tests for ydk.core.task_validator — DAG validation and coverage checking."""

from ydk.core.task_validator import check_coverage, validate_dag
from ydk.models.task import Task


class TestValidateDag:
    def test_no_deps_all_in_wave_1(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C"),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 1
        assert sorted(result.parallel_sets[0]) == ["T-001", "T-002", "T-003"]

    def test_linear_chain_one_per_wave(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
            Task(id="T-003", title="C", depends_on=["T-002"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 3
        assert result.parallel_sets[0] == ["T-001"]
        assert result.parallel_sets[1] == ["T-002"]
        assert result.parallel_sets[2] == ["T-003"]

    def test_detects_cycle(self) -> None:
        tasks = [
            Task(id="T-001", title="A", depends_on=["T-002"]),
            Task(id="T-002", title="B", depends_on=["T-001"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.cycles is not None
        assert len(result.cycles) > 0

    def test_computes_parallel_sets_correctly(self) -> None:
        #   T-001 ---> T-003
        #   T-002 --/
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B"),
            Task(id="T-003", title="C", depends_on=["T-001", "T-002"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 2
        assert sorted(result.parallel_sets[0]) == ["T-001", "T-002"]
        assert result.parallel_sets[1] == ["T-003"]

    def test_computes_critical_path(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
            Task(id="T-003", title="C", depends_on=["T-002"]),
        ]
        result = validate_dag(tasks)
        assert result.critical_path == ["T-001", "T-002", "T-003"]
        assert result.critical_path_length == 3

    def test_computes_fan_out(self) -> None:
        tasks = [
            Task(id="T-001", title="A"),
            Task(id="T-002", title="B", depends_on=["T-001"]),
            Task(id="T-003", title="C", depends_on=["T-001"]),
            Task(id="T-004", title="D", depends_on=["T-001"]),
        ]
        result = validate_dag(tasks)
        assert result.fan_out["T-001"] == 3

    def test_methodology_example(self) -> None:
        """Methodology example: T01-T07 from methodology docs.

        T01 (setup) -> T02 (data model), T03 (API routes)
        T02 -> T04 (business logic)
        T03 -> T04
        T04 -> T05 (integration)
        T04 -> T06 (notifications)
        T05, T06 -> T07 (e2e tests)
        """
        tasks = [
            Task(id="T01", title="Project setup"),
            Task(id="T02", title="Data model", depends_on=["T01"]),
            Task(id="T03", title="API routes", depends_on=["T01"]),
            Task(id="T04", title="Business logic", depends_on=["T02", "T03"]),
            Task(id="T05", title="Integration", depends_on=["T04"]),
            Task(id="T06", title="Notifications", depends_on=["T04"]),
            Task(id="T07", title="E2E tests", depends_on=["T05", "T06"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert result.cycles is None

        # Wave 1: T01, Wave 2: T02+T03, Wave 3: T04, Wave 4: T05+T06, Wave 5: T07
        assert len(result.parallel_sets) == 5
        assert result.parallel_sets[0] == ["T01"]
        assert sorted(result.parallel_sets[1]) == ["T02", "T03"]
        assert result.parallel_sets[2] == ["T04"]
        assert sorted(result.parallel_sets[3]) == ["T05", "T06"]
        assert result.parallel_sets[4] == ["T07"]

        # Critical path: T01 -> T02 or T03 -> T04 -> T05 or T06 -> T07 (length 5)
        assert result.critical_path_length == 5

        # Fan-out
        assert result.fan_out["T01"] == 2
        assert result.fan_out["T04"] == 2

    def test_empty_tasks(self) -> None:
        result = validate_dag([])
        assert result.valid is True
        assert result.parallel_sets == []
        assert result.critical_path == []

    def test_unresolved_dependencies_no_crash(self) -> None:
        """validate_dag must not crash when dependency IDs don't match any task."""
        tasks = [
            Task(id="42", title="A", depends_on=["T-684"]),
            Task(id="43", title="B"),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.error is not None
        assert "Unresolved" in result.error
        assert "T-684" in result.error
        # Unresolved deps are NOT cycles
        assert result.cycles is None

    def test_github_style_issue_number_ids(self) -> None:
        """DAG validation works with GitHub-style numeric issue IDs."""
        tasks = [
            Task(id="100", title="Setup"),
            Task(id="101", title="Model", depends_on=["100"]),
            Task(id="102", title="Routes", depends_on=["100"]),
            Task(id="103", title="Integration", depends_on=["101", "102"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is True
        assert len(result.parallel_sets) == 3
        assert result.parallel_sets[0] == ["100"]
        assert sorted(result.parallel_sets[1]) == ["101", "102"]
        assert result.parallel_sets[2] == ["103"]

    def test_multiple_unresolved_deps_reported(self) -> None:
        """All unresolved dependency IDs should be reported."""
        tasks = [
            Task(id="A", title="A", depends_on=["X", "Y"]),
            Task(id="B", title="B", depends_on=["Z"]),
        ]
        result = validate_dag(tasks)
        assert result.valid is False
        assert result.error is not None
        assert "X" in result.error
        assert "Y" in result.error
        assert "Z" in result.error
        assert result.cycles is None


class TestCheckCoverage:
    def test_finds_uncovered_sections(self) -> None:
        spec_sections = {
            "auth": ["login", "logout"],
            "billing": ["charge", "refund"],
            "notifications": ["email"],
        }
        story_refs = {
            "auth": {"S-001", "S-002"},
            "billing": {"S-003"},
            # notifications not covered
        }
        uncovered = check_coverage(spec_sections, story_refs)
        assert uncovered == ["notifications"]

    def test_passes_when_all_covered(self) -> None:
        spec_sections = {"auth": ["login"], "billing": ["charge"]}
        story_refs = {"auth": {"S-001"}, "billing": {"S-002"}}
        assert check_coverage(spec_sections, story_refs) == []

    def test_handles_empty_inputs(self) -> None:
        assert check_coverage({}, {}) == []
        assert check_coverage({}, {"auth": {"S-001"}}) == []

    def test_empty_story_set_counts_as_uncovered(self) -> None:
        spec_sections = {"auth": ["login"]}
        story_refs = {"auth": set()}
        assert check_coverage(spec_sections, story_refs) == ["auth"]
