"""Tests for CLI parsing of dependency type syntax: T-001:validates."""

from ydk.cli.task_cmd import _parse_depends_on_arg
from ydk.models.pm import Dependency, DependencyType


class TestParseDependsOnArg:
    def test_bare_id_defaults_to_blocks(self) -> None:
        result = _parse_depends_on_arg(["T-001"])
        assert len(result) == 1
        assert result[0] == "T-001"

    def test_typed_dependency_parses_colon_syntax(self) -> None:
        result = _parse_depends_on_arg(["T-001:validates"])
        assert len(result) == 1
        assert isinstance(result[0], Dependency)
        assert result[0].task_id == "T-001"
        assert result[0].type == DependencyType.VALIDATES

    def test_blocks_type_returns_bare_string(self) -> None:
        """blocks is the default, so T-001:blocks should just return 'T-001'."""
        result = _parse_depends_on_arg(["T-001:blocks"])
        assert result[0] == "T-001"

    def test_mixed_bare_and_typed(self) -> None:
        result = _parse_depends_on_arg(["T-001", "T-002:caused-by", "T-003:waits-for"])
        assert result[0] == "T-001"
        assert isinstance(result[1], Dependency)
        assert result[1].type == DependencyType.CAUSED_BY
        assert isinstance(result[2], Dependency)
        assert result[2].type == DependencyType.WAITS_FOR

    def test_all_types_parse(self) -> None:
        for dep_type in DependencyType:
            result = _parse_depends_on_arg([f"T-001:{dep_type.value}"])
            if dep_type == DependencyType.BLOCKS:
                assert result[0] == "T-001"
            else:
                assert isinstance(result[0], Dependency)
                assert result[0].type == dep_type

    def test_empty_list(self) -> None:
        assert _parse_depends_on_arg([]) == []
