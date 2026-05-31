"""Tests for bypass prevention guard plugins.

Each test creates a Verifier targeting the specific plugin, feeds it context JSON,
and verifies pass/fail behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

VERIFICATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "odk" / "verifications"


def _run_guard_plugin(plugin_name: str, context: dict) -> tuple[bool, str]:
    """Run a guard plugin directly via subprocess and return (passed, output)."""
    check_script = VERIFICATIONS_DIR / plugin_name / "check.py"
    result = subprocess.run(
        [sys.executable, str(check_script)],
        input=json.dumps(context),
        capture_output=True,
        text=True,
        timeout=5,
    )
    data = json.loads(result.stdout)
    return data["passed"], data["output"]


class TestNoNoqa:
    """Tests for the guard-no-noqa plugin."""

    def test_blocks_noqa_in_source(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "src/app/service.py",
                "new_content": "x = 1  # noqa: E501\n",
            },
        )
        assert passed is False
        assert "Fix the violation" in output

    def test_blocks_type_ignore(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "src/app/service.py",
                "new_content": "result: Any = foo()  # type: ignore[assignment]\n",
            },
        )
        assert passed is False
        assert "Fix the violation" in output

    def test_blocks_nosec(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "src/app/service.py",
                "new_content": "password = 'secret'  # nosec\n",
            },
        )
        assert passed is False
        assert "Fix the violation" in output

    def test_allows_normal_code(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "src/app/service.py",
                "new_content": "def hello() -> str:\n    return 'world'\n",
            },
        )
        assert passed is True

    def test_allows_ann_noqa_in_tests(self) -> None:
        """Tests are exempt from annotation-rule (ANN*) noqa comments."""
        passed, _ = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "tests/test_foo.py",
                "new_content": "def test_something(fixture):  # noqa: ANN001\n    pass\n",
            },
        )
        assert passed is True

    def test_blocks_non_ann_noqa_in_tests(self) -> None:
        """Non-ANN noqa in tests is still blocked."""
        passed, _ = _run_guard_plugin(
            "guard-no-noqa",
            {
                "file_path": "tests/test_foo.py",
                "new_content": "x = 1  # noqa: E501\n",
            },
        )
        assert passed is False


class TestNoMockInternals:
    """Tests for the guard-no-mock-internals plugin."""

    def test_blocks_patch_app(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": '@patch("app.services.user.UserService")\ndef test_x(): pass\n',
            },
        )
        assert passed is False
        assert "system boundaries" in output

    def test_blocks_patch_src(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": "@patch('src.core.engine.Engine')\ndef test_x(): pass\n",
            },
        )
        assert passed is False
        assert "system boundaries" in output

    def test_blocks_magicmock_with_internal_spec(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": "mock = MagicMock(spec=app.services.UserService)\n",
            },
        )
        assert passed is False

    def test_allows_patch_boto3(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": '@patch("boto3.client")\ndef test_x(): pass\n',
            },
        )
        assert passed is True

    def test_allows_patch_subprocess(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": '@patch("subprocess.run")\ndef test_x(): pass\n',
            },
        )
        assert passed is True

    def test_allows_non_test_files(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "src/app/service.py",
                "new_content": '@patch("app.services.user.UserService")\ndef test_x(): pass\n',
            },
        )
        assert passed is True

    def test_allows_magicmock_without_internal_spec(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-mock-internals",
            {
                "file_path": "tests/test_service.py",
                "new_content": "mock = MagicMock()\nmock.do_thing.return_value = 42\n",
            },
        )
        assert passed is True


class TestNoManualPr:
    """Tests for the guard-no-manual-pr plugin."""

    def test_blocks_gh_pr_create(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-manual-pr",
            {
                "command": "gh pr create --title 'Fix bug' --body 'Done'",
            },
        )
        assert passed is False
        assert "odk task done" in output

    def test_blocks_gh_pr_merge(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-manual-pr",
            {
                "command": "gh pr merge 42 --squash",
            },
        )
        assert passed is False
        assert "odk task done" in output

    def test_allows_gh_issue_create(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-manual-pr",
            {
                "command": "gh issue create --title 'Bug report'",
            },
        )
        assert passed is True

    def test_allows_other_commands(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-manual-pr",
            {
                "command": "uv run pytest tests/ -q",
            },
        )
        assert passed is True


class TestNoProofTamper:
    """Tests for the guard-no-proof-tamper plugin."""

    def test_blocks_edit_to_proof_files(self) -> None:
        passed, output = _run_guard_plugin(
            "guard-no-proof-tamper",
            {
                "file_path": ".odk/proofs/T-001/verification.json",
                "new_content": '{"tampered": true}',
            },
        )
        assert passed is False
        assert "odk task done" in output

    def test_allows_summary_md(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-proof-tamper",
            {
                "file_path": ".odk/proofs/T-001/summary.md",
                "new_content": "# Summary\nAll tests pass.",
            },
        )
        assert passed is True

    def test_allows_non_proof_paths(self) -> None:
        passed, _ = _run_guard_plugin(
            "guard-no-proof-tamper",
            {
                "file_path": "src/app/main.py",
                "new_content": "print('hello')\n",
            },
        )
        assert passed is True
