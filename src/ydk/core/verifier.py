"""Plugin-based verification runner.

Discovers verification plugins from folder-based manifests
and runs them by piping JSON context to stdin, reading JSON results from stdout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import yaml

from ydk.core.verification_cache import VerificationCache
from ydk.models.verification import CheckResult, VerificationReport

logger = logging.getLogger("ydk.verifier")


class VerificationContractError(Exception):
    """Raised when a verification plugin violates the JSON contract."""


# Required fields in the JSON output from a verification plugin
_REQUIRED_OUTPUT_FIELDS = {"name", "passed", "output"}


@dataclass
class VerificationPlugin:
    """Represents a discovered verification plugin."""

    name: str
    description: str
    trigger: str
    parallel: bool
    timeout: int
    requires: list[str]
    check_script: Path
    supports_auto_fix: bool = False


class Verifier:
    """Plugin-based verification runner.

    Discovers plugins from two directories:
    - project_verifications: project-specific (e.g. .ydk/verifications/)
    - global_verifications: ships with YDK (e.g. ydk/verifications/)

    Project plugins override global plugins with the same name.
    """

    def __init__(
        self,
        project_root: Path = Path("."),
        global_verifications: Path | None = None,
        project_verifications: Path | None = None,
        enabled_plugins: list[str] | None = None,
        *,
        use_cache: bool = True,
    ) -> None:
        self._root = project_root
        self._global = global_verifications or (Path(__file__).resolve().parent.parent / "verifications")
        self._project = project_verifications or (project_root / ".ydk" / "verifications")
        self._enabled = enabled_plugins  # None = run all; [] = none; [...] = filter
        self._use_cache = use_cache
        self._cache = VerificationCache(project_root / ".ydk" / "cache" / "verification")

    @property
    def cache(self) -> VerificationCache:
        """Expose the underlying cache for direct operations."""
        return self._cache

    def discover_plugins(self) -> list[VerificationPlugin]:
        """Find all verification plugins. Project-specific first, then global.

        Project plugins override global plugins with the same name.
        When *enabled_plugins* was set at init time, only those plugins are returned.
        """
        seen: set[str] = set()
        plugins: list[VerificationPlugin] = []
        for search_dir in (self._project, self._global):
            if not search_dir.is_dir():
                continue
            for child in sorted(search_dir.iterdir()):
                manifest_path = child / "manifest.yaml"
                check_path = child / "check.py"
                if child.is_dir() and manifest_path.exists() and check_path.exists():
                    plugin = self._load_plugin(manifest_path, check_path)
                    if plugin.name not in seen:
                        seen.add(plugin.name)
                        plugins.append(plugin)

        # If an enabled list was provided, filter to only those plugins
        if self._enabled is not None:
            enabled_set = set(self._enabled)
            plugins = [p for p in plugins if p.name in enabled_set]

        return plugins

    def filter_by_trigger(self, plugins: list[VerificationPlugin], trigger: str) -> list[VerificationPlugin]:
        """Get plugins for a specific trigger ID (e.g. ``git:pre-commit``).

        Accepts shorthand forms like ``pre-commit`` and normalizes them
        to the canonical ``git:pre-commit`` form before matching.
        """
        normalized = _normalize_trigger(trigger)
        return [p for p in plugins if p.trigger == normalized]

    def filter_by_name(self, plugins: list[VerificationPlugin], name: str) -> list[VerificationPlugin]:
        """Get a specific plugin by name."""
        return [p for p in plugins if p.name == name]

    async def run_plugin(
        self,
        plugin: VerificationPlugin,
        context: dict[str, Any],
        *,
        auto_fix: bool = False,
    ) -> CheckResult:
        """Run a single plugin: pipe context as JSON to stdin, parse JSON from stdout.

        When *auto_fix* is ``True`` and the plugin declares ``supports_auto_fix``,
        the ``auto_fix`` key is injected into the context so the plugin can run
        its fix commands before checking.

        Raises :class:`VerificationContractError` for:
        - Missing required context fields (``project_root``)
        - Invalid JSON output from the plugin
        - Missing required output fields (``name``, ``passed``, ``output``)
        """
        # Validate required context fields before running
        missing_ctx = {"project_root"} - set(context.keys())
        if missing_ctx:
            raise VerificationContractError(
                f"Context missing required fields for plugin {plugin.name!r}: {', '.join(sorted(missing_ctx))}"
            )

        # Inject auto_fix into context only for plugins that support it
        plugin_context = dict(context)
        if auto_fix and plugin.supports_auto_fix:
            plugin_context["auto_fix"] = True
        else:
            plugin_context.pop("auto_fix", None)

        # Cache lookup - hash all Python files under the project root
        file_hashes: dict[str, str] = {}
        if self._use_cache:
            py_files = sorted(self._root.rglob("*.py"))
            file_hashes = VerificationCache.compute_hash(py_files)
            cached = self._cache.get_cached(plugin.name, file_hashes)
            if cached is not None:
                return cached

        logger.info("Running plugin %s", plugin.name)
        start = time.time()
        try:
            result = self._run_check_script(plugin, plugin_context)
            elapsed = time.time() - start
            logger.info(
                "Plugin %s %s in %.1fs",
                plugin.name,
                "passed" if result.passed else "FAILED",
                elapsed,
            )
            if self._use_cache:
                self._cache.store(plugin.name, file_hashes, result)
            return result
        except subprocess.TimeoutExpired:
            return CheckResult(
                name=plugin.name,
                passed=False,
                output=f"Plugin timed out after {plugin.timeout}s",
                duration_seconds=round(time.time() - start, 1),
            )
        except json.JSONDecodeError as exc:
            return CheckResult(
                name=plugin.name,
                passed=False,
                output=f"Plugin returned invalid JSON: {exc}",
                duration_seconds=round(time.time() - start, 1),
            )
        except VerificationContractError:
            return CheckResult(
                name=plugin.name,
                passed=False,
                output=f"Plugin {plugin.name!r} violated verification contract",
                duration_seconds=round(time.time() - start, 1),
            )
        except KeyError as exc:
            return CheckResult(
                name=plugin.name,
                passed=False,
                output=f"Plugin returned invalid JSON — missing required field: {exc}",
                duration_seconds=round(time.time() - start, 1),
            )
        except FileNotFoundError:
            return CheckResult(
                name=plugin.name,
                passed=False,
                output=f"Check script not found: {plugin.check_script}",
                duration_seconds=round(time.time() - start, 1),
            )

    def run_guard(self, trigger: str, context: dict[str, Any]) -> tuple[bool, str]:
        """Run guard plugins synchronously. Returns (all_passed, first_failure_message)."""
        plugins = self.discover_plugins()
        guard_plugins = [p for p in plugins if p.trigger == trigger]

        for plugin in guard_plugins:
            try:
                result = self._run_check_script(plugin, context)
                if not result.passed:
                    return False, result.output
            except (VerificationContractError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
                return False, f"Guard plugin {plugin.name!r} error: {exc}"

        return True, ""

    def _run_check_script(self, plugin: VerificationPlugin, context: dict[str, Any]) -> CheckResult:
        """Execute check.py subprocess with JSON stdin/stdout protocol."""
        import sys as _sys

        input_json = json.dumps(context)
        result = subprocess.run(
            [_sys.executable, str(plugin.check_script)],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=plugin.timeout,
            cwd=str(self._root),
        )

        if result.returncode == 2:
            # Exit code 2 = error (not a check failure)
            raise VerificationContractError(
                f"Plugin {plugin.name!r} exited with code 2 (error): {(result.stderr or result.stdout).strip()}"
            )

        # Parse JSON from stdout — may raise json.JSONDecodeError
        data = json.loads(result.stdout)

        # Validate required output fields
        missing = _REQUIRED_OUTPUT_FIELDS - set(data.keys())
        if missing:
            raise VerificationContractError(
                f"Plugin {plugin.name!r} missing required output fields: {', '.join(sorted(missing))}"
            )

        return CheckResult(
            name=data["name"],
            passed=data["passed"],
            output=data["output"],
            duration_seconds=data.get("duration_seconds", 0.0),
            detail=data.get("detail"),
        )

    async def run_layer(
        self,
        plugins: list[VerificationPlugin],
        context: dict[str, Any],
        *,
        auto_fix: bool = False,
    ) -> list[CheckResult]:
        """Run a batch of plugins. Parallel where safe, serial where not."""
        parallel = [p for p in plugins if p.parallel]
        serial = [p for p in plugins if not p.parallel]

        results: list[CheckResult] = []

        # Run parallel plugins concurrently
        if parallel:
            parallel_results = await asyncio.gather(*(self.run_plugin(p, context, auto_fix=auto_fix) for p in parallel))
            results.extend(parallel_results)

        # Run serial plugins one at a time
        for p in serial:
            result = await self.run_plugin(p, context, auto_fix=auto_fix)
            results.append(result)

        return results

    def _get_changed_files(self) -> list[str] | None:
        """Get files changed on the current branch vs base (main)."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=str(self._root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()
        return None  # fallback to full project

    async def run_all(
        self,
        trigger: str = "manual",
        context: dict[str, Any] | None = None,
        *,
        auto_fix: bool = False,
        on_complete: Callable[[VerificationReport], None] | None = None,
    ) -> VerificationReport:
        """Run all plugins matching a trigger.

        When *on_complete* is provided, it is called with the final report
        after all checks finish.  This callback pattern allows integrations
        (e.g. PR commenting) without coupling the verifier to external services.
        """
        start = time.time()
        all_checks: list[CheckResult] = []

        if context is None:
            context = {"project_root": str(self._root)}
        if "project_root" not in context:
            context["project_root"] = str(self._root)

        # Inject changed files for scoping verifications to task branch
        if "changed_files" not in context:
            context["changed_files"] = self._get_changed_files()

        plugins = self.discover_plugins()
        normalized_trigger = _normalize_trigger(trigger)
        if normalized_trigger != "manual":
            plugins = self.filter_by_trigger(plugins, normalized_trigger)

        logger.info("Running %d plugin(s) for trigger %r", len(plugins), trigger)

        # Run all matched plugins in a single batch
        results = await self.run_layer(plugins, context, auto_fix=auto_fix)
        all_checks.extend(results)

        report = self._build_report(all_checks, start)
        logger.info(
            "Verification complete in %.1fs — %s",
            report.total_duration_seconds,
            "all passed" if report.all_passed else "FAILURES detected",
        )
        if on_complete is not None:
            on_complete(report)
        return report

    def _build_report(self, checks: list[CheckResult], start_time: float) -> VerificationReport:
        import time as _time

        return VerificationReport(
            timestamp=_time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            checks=checks,
            all_passed=all(c.passed for c in checks),
            total_duration_seconds=round(time.time() - start_time, 1),
        )

    def save_proof(self, report: VerificationReport, task_id: str | None = None) -> Path:
        """Save proof artifact to .ydk/proofs/."""
        proofs_dir = self._root / ".ydk" / "proofs"
        if task_id:
            proofs_dir = proofs_dir / task_id
        proofs_dir.mkdir(parents=True, exist_ok=True)

        path = proofs_dir / "verification.json"
        path.write_text(report.model_dump_json(indent=2))
        return path

    def _load_plugin(self, manifest_path: Path, check_path: Path) -> VerificationPlugin:
        """Load a single plugin from its manifest.yaml and check.py."""
        data = yaml.safe_load(manifest_path.read_text())
        return VerificationPlugin(
            name=data["name"],
            description=data.get("description", ""),
            trigger=_migrate_trigger(data),
            parallel=data.get("parallel", True),
            timeout=data.get("timeout", 30),
            requires=data.get("requires", []),
            check_script=check_path,
            supports_auto_fix=data.get("supports_auto_fix", False),
        )


def _normalize_trigger(trigger: str) -> str:
    """Normalize a trigger string to its canonical form.

    Accepts shorthand (``pre-commit``, ``pre-push``) and returns the
    canonical form (``git:pre-commit``, ``git:pre-push``).  Already-qualified
    triggers (containing ``:``) are returned as-is.
    """
    _SHORTHAND_MAP: dict[str, str] = {
        "pre-commit": "git:pre-commit",
        "pre-push": "git:pre-push",
        "manual": "manual",
    }
    if ":" in trigger:
        return trigger
    return _SHORTHAND_MAP.get(trigger, f"git:{trigger}")


def _migrate_trigger(data: dict[str, Any]) -> str:
    """Convert old manifest trigger formats to a single trigger ID string."""
    _OLD_TRIGGER_MAP: dict[str, str] = {
        "pre-commit": "git:pre-commit",
        "pre-push": "git:pre-push",
        "manual": "manual:run",
    }
    _LAYER_DEFAULTS: dict[int, str] = {1: "git:pre-commit", 2: "git:pre-push", 3: "git:pre-push"}
    raw = data.get("trigger")
    if raw is None:
        layer = data.get("layer", 1)
        return _LAYER_DEFAULTS.get(layer, "git:pre-push")
    if isinstance(raw, str) and ":" in raw:
        return raw
    if isinstance(raw, str):
        return _OLD_TRIGGER_MAP.get(raw, f"git:{raw}")
    if isinstance(raw, list) and len(raw) > 0:
        first = raw[0]
        return _OLD_TRIGGER_MAP.get(first, f"git:{first}")
    return "git:pre-commit"
