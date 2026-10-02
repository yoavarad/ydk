"""Doctor — health check business logic."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import ValidationError

from ydk.models.config import YdkConfig


class CheckSeverity(StrEnum):
    """Severity level for a health-check result."""

    ok = "ok"
    warning = "warning"
    error = "error"


@dataclass
class CheckResult:
    """Outcome of a single doctor health check."""

    name: str
    severity: CheckSeverity
    message: str
    detail: str | None = None


class Doctor:
    """Runs project health checks and reports issues."""

    def __init__(self, project_root: Path = Path(".")) -> None:
        self._root = project_root

    def run_all(self) -> list[CheckResult]:
        """Run all health checks. Returns list of results."""
        checks = [
            self._check_python,
            self._check_git,
            self._check_git_repo,
            self._check_ydk_config,
            self._check_spec_location,
            self._check_adrs_location,
            self._check_project_rules,
            self._check_test_runner,
            self._check_linter,
            self._check_type_checker,
            self._check_remote_cli,
            self._check_gh_auth,
            self._check_gh_repo,
            self._check_gh_labels,
            self._check_jinja2,
            self._check_task_pr_drift,
            self._check_epic_retros,
        ]
        return [check() for check in checks]

    def has_errors(self, results: list[CheckResult]) -> bool:
        """Return True if any result has error severity."""
        return any(r.severity == CheckSeverity.error for r in results)

    def has_warnings(self, results: list[CheckResult]) -> bool:
        """Return True if any result has warning severity."""
        return any(r.severity == CheckSeverity.warning for r in results)

    # -- individual checks --------------------------------------------------

    def _check_python(self) -> CheckResult:
        """Check Python >= 3.13."""
        import sys

        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info >= (3, 13):  # noqa: UP036
            return CheckResult("Python", CheckSeverity.ok, f"Python {version}")
        return CheckResult("Python", CheckSeverity.error, f"Python {version} — requires >= 3.13")

    def _check_git(self) -> CheckResult:
        """Check git CLI is installed."""
        if shutil.which("git"):
            try:
                out = subprocess.run(
                    ["git", "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                version = out.stdout.strip()
                return CheckResult("Git", CheckSeverity.ok, version)
            except Exception:
                return CheckResult("Git", CheckSeverity.ok, "git found")
        return CheckResult("Git", CheckSeverity.error, "git not found")

    def _check_git_repo(self) -> CheckResult:
        """Check we're inside a git repository."""
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                cwd=self._root,
            )
            if out.returncode == 0:
                return CheckResult("Git repo", CheckSeverity.ok, "Inside a git repository")
            return CheckResult("Git repo", CheckSeverity.error, "Not inside a git repository")
        except Exception:
            return CheckResult("Git repo", CheckSeverity.error, "Could not check git repository")

    def _check_ydk_config(self) -> CheckResult:
        """Check .ydk/config.yaml exists and is valid."""
        config_path = self._root / ".ydk" / "config.yaml"
        if not config_path.is_file():
            return CheckResult(
                "YDK config",
                CheckSeverity.error,
                ".ydk/config.yaml not found",
                detail="Run 'ydk init' to create it",
            )
        try:
            raw = yaml.safe_load(config_path.read_text())
            YdkConfig.model_validate(raw)
            return CheckResult("YDK config", CheckSeverity.ok, ".ydk/config.yaml is valid")
        except (yaml.YAMLError, ValidationError, Exception) as exc:
            return CheckResult(
                "YDK config",
                CheckSeverity.error,
                ".ydk/config.yaml is invalid",
                detail=str(exc)[:200],
            )

    def _load_config_safe(self) -> YdkConfig | None:
        """Try to load config; return None on failure."""
        config_path = self._root / ".ydk" / "config.yaml"
        if not config_path.is_file():
            return None
        try:
            raw = yaml.safe_load(config_path.read_text())
            return YdkConfig.model_validate(raw)
        except Exception:
            return None

    def _check_spec_location(self) -> CheckResult:
        """Check configured spec directory exists."""
        config = self._load_config_safe()
        if config is None:
            return CheckResult(
                "Spec location",
                CheckSeverity.warning,
                "Cannot check — config not loaded",
            )
        spec_dir = self._root / config.project.spec_location
        if spec_dir.is_dir():
            count = len(list(spec_dir.glob("*.md")))
            return CheckResult(
                "Spec location",
                CheckSeverity.ok,
                f"{config.project.spec_location}/ exists ({count} .md files)",
            )
        return CheckResult(
            "Spec location",
            CheckSeverity.warning,
            f"{config.project.spec_location}/ not found",
            detail="Run 'ydk init' or create it manually",
        )

    def _check_adrs_location(self) -> CheckResult:
        """Check configured ADRs directory exists."""
        config = self._load_config_safe()
        if config is None:
            return CheckResult(
                "ADRs location",
                CheckSeverity.warning,
                "Cannot check — config not loaded",
            )
        adrs_dir = self._root / config.project.adrs_location
        if adrs_dir.is_dir():
            return CheckResult(
                "ADRs location",
                CheckSeverity.ok,
                f"{config.project.adrs_location}/ exists",
            )
        return CheckResult(
            "ADRs location",
            CheckSeverity.warning,
            f"{config.project.adrs_location}/ not found",
        )

    def _check_project_rules(self) -> CheckResult:
        """Check docs/project-rules.md exists."""
        rules_file = self._root / "docs" / "project-rules.md"
        if rules_file.is_file():
            return CheckResult("Project rules", CheckSeverity.ok, "docs/project-rules.md exists")
        return CheckResult(
            "Project rules",
            CheckSeverity.warning,
            "docs/project-rules.md not found",
        )

    def _check_test_runner(self) -> CheckResult:
        """Check pytest is available."""
        if shutil.which("pytest"):
            return CheckResult("Test runner", CheckSeverity.ok, "pytest available")
        try:
            import importlib.util

            if importlib.util.find_spec("pytest") is not None:
                return CheckResult("Test runner", CheckSeverity.ok, "pytest importable")
        except Exception:
            pass
        return CheckResult("Test runner", CheckSeverity.warning, "pytest not found")

    def _check_linter(self) -> CheckResult:
        """Check ruff is available."""
        if shutil.which("ruff"):
            return CheckResult("Linter", CheckSeverity.ok, "ruff available")
        return CheckResult("Linter", CheckSeverity.warning, "ruff not found")

    def _check_type_checker(self) -> CheckResult:
        """Check ty or mypy is available."""
        if shutil.which("ty"):
            return CheckResult("Type checker", CheckSeverity.ok, "ty available")
        if shutil.which("mypy"):
            return CheckResult("Type checker", CheckSeverity.ok, "mypy available")
        return CheckResult("Type checker", CheckSeverity.warning, "No type checker found (ty or mypy)")

    def _check_remote_cli(self) -> CheckResult:
        """Check gh or glab is available based on config."""
        config = self._load_config_safe()
        remote = config.project.remote if config else "github"
        if remote == "github":
            if shutil.which("gh"):
                return CheckResult("Remote CLI", CheckSeverity.ok, "gh available")
            return CheckResult(
                "Remote CLI",
                CheckSeverity.warning,
                "gh not found — local mode only",
            )
        if shutil.which("glab"):
            return CheckResult("Remote CLI", CheckSeverity.ok, "glab available")
        return CheckResult(
            "Remote CLI",
            CheckSeverity.warning,
            "glab not found — local mode only",
        )

    def _gh_skip_reason(self) -> str | None:
        """Reason to skip a gh-dependent check, or None if gh checks should run.

        Uses the same "github" fallback as `_check_remote_cli` when config
        fails to load, so all gh-related checks agree on the no-config case.
        """
        config = self._load_config_safe()
        remote = config.project.remote if config else "github"
        if remote != "github":
            return "remote is not github"
        if shutil.which("gh") is None:
            return "gh not found"
        return None

    def _check_gh_auth(self) -> CheckResult:
        """Check gh CLI is authenticated (github remote only)."""
        skip_reason = self._gh_skip_reason()
        if skip_reason is not None:
            return CheckResult("GitHub auth", CheckSeverity.ok, f"Skipped — {skip_reason}")
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=self._root,
        )
        if result.returncode == 0:
            return CheckResult("GitHub auth", CheckSeverity.ok, "gh is authenticated")
        return CheckResult(
            "GitHub auth",
            CheckSeverity.error,
            "gh is not authenticated",
            detail=(result.stderr or result.stdout).strip()[:200],
        )

    def _check_gh_repo(self) -> CheckResult:
        """Check gh can resolve the repo and issues are enabled (github remote only)."""
        skip_reason = self._gh_skip_reason()
        if skip_reason is not None:
            return CheckResult("GitHub repo", CheckSeverity.ok, f"Skipped — {skip_reason}")
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner,hasIssuesEnabled"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=self._root,
        )
        if result.returncode != 0:
            return CheckResult(
                "GitHub repo",
                CheckSeverity.error,
                "gh repo view failed — repo not accessible",
                detail=result.stderr.strip()[:200],
            )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return CheckResult("GitHub repo", CheckSeverity.warning, "Could not parse gh repo view output")
        name = data.get("nameWithOwner", "repo")
        if not data.get("hasIssuesEnabled", True):
            return CheckResult("GitHub repo", CheckSeverity.warning, f"Issues are disabled on {name}")
        return CheckResult("GitHub repo", CheckSeverity.ok, f"{name} accessible, issues enabled")

    def _check_gh_labels(self) -> CheckResult:
        """Check required labels exist on the remote (github remote only)."""
        skip_reason = self._gh_skip_reason()
        if skip_reason is not None:
            return CheckResult("GitHub labels", CheckSeverity.ok, f"Skipped — {skip_reason}")

        from ydk.repositories.github._helpers import REQUIRED_LABELS

        result = subprocess.run(
            ["gh", "label", "list", "--json", "name"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=self._root,
        )
        if result.returncode != 0:
            return CheckResult(
                "GitHub labels",
                CheckSeverity.warning,
                "Could not list labels",
                detail=result.stderr.strip()[:200],
            )
        try:
            existing = {item["name"] for item in json.loads(result.stdout)}
        except (json.JSONDecodeError, TypeError, KeyError):
            return CheckResult("GitHub labels", CheckSeverity.warning, "Could not parse label list")
        missing = [name for name, _color, _description in REQUIRED_LABELS if name not in existing]
        if missing:
            return CheckResult(
                "GitHub labels",
                CheckSeverity.warning,
                f"{len(missing)} required label(s) missing",
                detail=", ".join(missing),
            )
        return CheckResult("GitHub labels", CheckSeverity.ok, "All required labels present")

    def _check_jinja2(self) -> CheckResult:
        """Check Jinja2 is importable."""
        try:
            import jinja2  # noqa: F401

            return CheckResult("Jinja2", CheckSeverity.ok, "Jinja2 available")
        except ImportError:
            return CheckResult("Jinja2", CheckSeverity.warning, "Jinja2 not installed")

    def _check_task_pr_drift(self) -> CheckResult:
        """Flag tasks whose status disagrees with their PR's real merge state."""
        if shutil.which("gh") is None:
            return CheckResult(
                "Task/PR drift",
                CheckSeverity.ok,
                "Skipped — gh not found (local mode only)",
            )

        try:
            from ydk.repositories.factory import get_task_repository

            repo = get_task_repository()
            summaries = repo.list_tasks(state="all")
        except Exception:
            return CheckResult(
                "Task/PR drift",
                CheckSeverity.warning,
                "Could not check — task repository unavailable",
            )

        candidates = [s for s in summaries if s.status in ("open", "in-review")]
        if not candidates:
            return CheckResult("Task/PR drift", CheckSeverity.ok, "No task/PR status drift detected")

        from ydk.core.task_pr_lookup import find_task_pr, list_prs

        prs = list_prs()
        drifted = []
        for s in candidates:
            pr = find_task_pr(s.id, prs=prs)
            if pr is not None and pr.get("state") == "MERGED":
                drifted.append(f"{s.id} is {s.status} but PR #{pr['number']} merged — run: ydk task close {s.id}")

        if not drifted:
            return CheckResult("Task/PR drift", CheckSeverity.ok, "No task/PR status drift detected")

        return CheckResult(
            "Task/PR drift",
            CheckSeverity.warning,
            f"{len(drifted)} task(s) with merged PRs not marked done",
            detail="\n".join(drifted),
        )

    def _check_epic_retros(self) -> CheckResult:
        """Warn about finished epics with no retrospective recorded."""
        try:
            from ydk.core.config import load_config
            from ydk.core.retro_gate import find_epics_missing_retro
            from ydk.repositories.factory import get_epic_repository

            if not load_config().learning.require_epic_retro:
                return CheckResult(
                    "Epic retrospectives",
                    CheckSeverity.ok,
                    "Skipped — learning.require_epic_retro disabled",
                )
            missing = find_epics_missing_retro(get_epic_repository())
        except Exception:
            return CheckResult(
                "Epic retrospectives",
                CheckSeverity.warning,
                "Could not check — epic repository unavailable",
            )

        if not missing:
            return CheckResult("Epic retrospectives", CheckSeverity.ok, "No missing epic retrospectives")

        detail = "\n".join(
            f'{m.epic_id} "{m.title}" -- run: ydk memory retrospective --epic {m.epic_id}' for m in missing
        )
        return CheckResult(
            "Epic retrospectives",
            CheckSeverity.warning,
            f"{len(missing)} finished epic(s) missing a retrospective",
            detail=detail,
        )
