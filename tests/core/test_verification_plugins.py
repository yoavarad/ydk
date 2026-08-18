"""Tests for verification plugin directory discovery logic."""

from __future__ import annotations

from pathlib import Path


class TestLintRuffDiscoverDirs:
    """Test that lint-ruff plugin discovers directories instead of hardcoding."""

    def test_discovers_src_and_tests(self, tmp_path: Path) -> None:
        """Plugin discovers src/ and tests/ when they exist."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"
        )
        # Import the function directly by executing the module code
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("lint_ruff_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        dirs = mod._discover_dirs(str(tmp_path))
        assert "src" in dirs
        assert "tests" in dirs

    def test_discovers_app_directory(self, tmp_path: Path) -> None:
        """Plugin discovers app/ when src/ doesn't exist."""
        (tmp_path / "app").mkdir()

        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("lint_ruff_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        dirs = mod._discover_dirs(str(tmp_path))
        assert "app" in dirs

    def test_falls_back_to_dot_when_no_dirs(self, tmp_path: Path) -> None:
        """Plugin falls back to '.' when no standard dirs exist."""
        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "lint-ruff" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("lint_ruff_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        dirs = mod._discover_dirs(str(tmp_path))
        assert dirs == ["."]


class TestTypesTyDiscoverDirs:
    """Test that types-ty plugin discovers source directories."""

    def test_discovers_src(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()

        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "types-ty" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("types_ty_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        dirs = mod._discover_src_dirs(str(tmp_path))
        assert "src" in dirs

    def test_falls_back_to_dot(self, tmp_path: Path) -> None:
        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "types-ty" / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("types_ty_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        dirs = mod._discover_src_dirs(str(tmp_path))
        assert dirs == ["."]

    def test_ty_check_uses_project_flag(self, tmp_path: Path) -> None:
        """ty check is called with --project to prevent scanning parent directories."""
        check_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "verifications" / "types-ty" / "check.py"
        )

        # Verify the --project flag is present in the source to constrain ty to the project dir.
        source = check_path.read_text()
        assert '"--project", project_root' in source or "'--project', project_root" in source


class TestTestsPytestDiscoverDirs:
    """Test that tests-pytest plugin discovers test directories."""

    def test_discovers_tests(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()

        check_path = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "ydk"
            / "verifications"
            / "tests-pytest"
            / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("tests_pytest_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        d = mod._discover_test_dir(str(tmp_path))
        assert d == "tests"

    def test_discovers_test_singular(self, tmp_path: Path) -> None:
        (tmp_path / "test").mkdir()

        check_path = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "ydk"
            / "verifications"
            / "tests-pytest"
            / "check.py"
        )
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("tests_pytest_check", check_path)
        assert spec is not None
        assert spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)

        d = mod._discover_test_dir(str(tmp_path))
        assert d == "test"
