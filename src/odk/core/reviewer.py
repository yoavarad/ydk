"""YAML-based parallel reviewer agents for spec verification.

Each reviewer criterion is defined by a YAML file containing:
- Inline Python tool code (compiled at load time via ``exec()``)
- A detailed system prompt
- Threshold and scoring metadata

Reviewers run concurrently via ``ThreadPoolExecutor``.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — used at runtime
from typing import Any

import yaml

try:
    from strands import tool as strands_tool

    HAS_STRANDS = True
except ImportError:
    HAS_STRANDS = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewerConfig:
    """Configuration for a single reviewer agent."""

    id: str
    name: str
    system_prompt: str
    tools: list[Any]  # list of callables compiled from YAML
    threshold: int = 8
    group: str = "quality"
    model_tier: str = "smart"


@dataclass(frozen=True)
class ReviewFinding:
    """A single finding from a reviewer agent."""

    line: int = 0
    text: str = ""
    issue: str = ""
    category: str = ""
    suggestion: str = ""


@dataclass(frozen=True)
class ReviewResult:
    """Result from a single reviewer agent."""

    reviewer_id: str
    name: str
    score: int
    passed: bool
    reasoning: str
    suggestions: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    debug_output: str = ""
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# YAML loading + inline code compilation
# ---------------------------------------------------------------------------


def _compile_tool(tool_def: dict[str, str]) -> object:
    """Compile an inline Python tool from a YAML tool definition.

    The ``code`` block must define exactly one function whose name
    matches the ``name`` field.  When Strands is available the raw
    function is wrapped with ``@tool`` so the Strands Agent can
    discover it; otherwise the plain callable is returned (sufficient
    for tools-only mode).
    """
    name = tool_def["name"]
    code = tool_def["code"]
    description = tool_def.get("description", "")
    namespace: dict[str, Any] = {}
    exec(compile(code, f"<reviewer-tool:{name}>", "exec"), namespace)
    func = namespace.get(name)
    if func is None:
        msg = f"Tool code for '{name}' did not define a function named '{name}'"
        raise ValueError(msg)

    if HAS_STRANDS:
        return strands_tool(name=name, description=description)(func)
    return func


def load_reviewer(yaml_path: Path) -> ReviewerConfig:
    """Load a single reviewer from a YAML file.

    Reads the YAML, compiles inline tool code, and returns a
    fully-initialised ``ReviewerConfig``.
    """
    raw = yaml.safe_load(yaml_path.read_text())

    tools = []
    for tool_def in raw.get("tools", []):
        try:
            tools.append(_compile_tool(tool_def))
        except Exception:
            logger.exception("Failed to compile tool '%s' in %s", tool_def.get("name"), yaml_path)

    return ReviewerConfig(
        id=raw["id"],
        name=raw["name"],
        system_prompt=raw["system_prompt"],
        tools=tools,
        threshold=raw.get("threshold", 8),
        group=raw.get("group", "quality"),
        model_tier=raw.get("model_tier", "smart"),
    )


def load_all_reviewers(
    reviewers_dir: Path,
    *,
    threshold_overrides: dict[str, int] | None = None,
) -> list[ReviewerConfig]:
    """Load all YAML reviewers from a directory.

    Args:
        reviewers_dir: Directory containing ``*.yaml`` reviewer files.
        threshold_overrides: Map of group name -> threshold override.

    Returns:
        Sorted list of ReviewerConfig instances.
    """
    overrides = threshold_overrides or {}
    configs: list[ReviewerConfig] = []

    yaml_files = sorted(reviewers_dir.glob("*.yaml"))
    for yf in yaml_files:
        try:
            cfg = load_reviewer(yf)
            # Apply threshold override if present for this group
            threshold = overrides.get(cfg.group, cfg.threshold)
            if threshold != cfg.threshold:
                cfg = ReviewerConfig(
                    id=cfg.id,
                    name=cfg.name,
                    system_prompt=cfg.system_prompt,
                    tools=cfg.tools,
                    threshold=threshold,
                    group=cfg.group,
                    model_tier=cfg.model_tier,
                )
            configs.append(cfg)
        except Exception:
            logger.exception("Failed to load reviewer from %s", yf)

    return configs


# ---------------------------------------------------------------------------
# ReviewerAgent — wraps a Strands Agent for one criterion
# ---------------------------------------------------------------------------


class ReviewerAgent:
    """Wraps a Strands Agent for a single verification criterion."""

    def __init__(self, config: ReviewerConfig, model_config: dict[str, Any]) -> None:
        self._config = config
        self._model_config = model_config

    def review(self, spec_content: str) -> ReviewResult:
        """Run the reviewer agent against spec content."""
        start = time.monotonic()
        logger.info("Starting reviewer %s (%s)", self._config.id, self._config.name)
        try:
            result = self._run_with_llm(spec_content)
            elapsed = time.monotonic() - start
            logger.info(
                "Reviewer %s completed in %.1fs — score %d/%d",
                self._config.id,
                elapsed,
                result.score,
                self._config.threshold,
            )
            return ReviewResult(
                reviewer_id=result.reviewer_id,
                name=result.name,
                score=result.score,
                passed=result.passed,
                reasoning=result.reasoning,
                suggestions=result.suggestions,
                findings=result.findings,
                debug_output=result.debug_output,
                elapsed_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(
                "Reviewer %s LLM failed after %.1fs: %s: %s",
                self._config.id,
                elapsed,
                type(exc).__name__,
                exc,
            )
            tools_result = self._run_tools_only(spec_content)
            error_msg = f"LLM FAILED: {type(exc).__name__}: {str(exc)[:200]}"
            return ReviewResult(
                reviewer_id=tools_result.reviewer_id,
                name=tools_result.name,
                score=tools_result.score,
                passed=tools_result.passed,
                reasoning=f"{error_msg} — Falling back to deterministic tools only. {tools_result.reasoning}",
                suggestions=tools_result.suggestions,
                findings=tools_result.findings,
                elapsed_seconds=elapsed,
            )

    def _run_with_llm(self, spec_content: str) -> ReviewResult:
        """Run with full Strands Agent (LLM + tools)."""
        import boto3
        from strands import Agent
        from strands.models.bedrock import BedrockModel

        logger.debug("Reviewer %s: creating Bedrock session", self._config.id)
        api_start = time.monotonic()
        session = boto3.Session(
            region_name=self._model_config.get("region", "us-east-1"),
            profile_name=self._model_config.get("profile") or None,
        )
        model = BedrockModel(
            model_id=self._model_config.get("model_id", "us.anthropic.claude-sonnet-4-6"),
            boto_session=session,
            temperature=0.0,
        )

        agent = Agent(
            model=model,
            system_prompt=self._config.system_prompt,
            tools=list(self._config.tools),
            callback_handler=None,
        )
        logger.debug(
            "Reviewer %s: Bedrock agent ready in %.1fs",
            self._config.id,
            time.monotonic() - api_start,
        )

        user_message = (
            "Here is the specification document to review:\n\n"
            "--- SPEC START ---\n"
            f"{spec_content}\n"
            "--- SPEC END ---\n\n"
            "Run your tools first on the spec content above, then apply your judgment. "
            "Return your assessment as JSON."
        )

        call_start = time.monotonic()
        response = agent(user_message)
        logger.debug(
            "Reviewer %s: Bedrock API call completed in %.1fs",
            self._config.id,
            time.monotonic() - call_start,
        )
        return self._parse_response(str(response))

    def _run_tools_only(self, spec_content: str) -> ReviewResult:
        """Run only deterministic tools (no LLM)."""
        all_findings: list[dict[str, Any]] = []
        for tool in self._config.tools:
            tool_name = getattr(tool, "__name__", str(tool))
            tool_start = time.monotonic()
            try:
                result_json = tool(spec_content)
                findings = json.loads(result_json)
                if isinstance(findings, list):
                    all_findings.extend(findings)
                elif isinstance(findings, dict):
                    all_findings.append(findings)
                logger.debug(
                    "Reviewer %s: tool %s completed in %.1fs — %d finding(s)",
                    self._config.id,
                    tool_name,
                    time.monotonic() - tool_start,
                    len(findings) if isinstance(findings, list) else 1,
                )
            except Exception:
                logger.exception(
                    "Tool %s failed after %.1fs",
                    tool_name,
                    time.monotonic() - tool_start,
                )

        # Deterministic scoring based on finding count
        finding_count = len(all_findings)
        if finding_count == 0:
            score = 10
        elif finding_count <= 3:
            score = 7
        elif finding_count <= 8:
            score = 4
        else:
            score = 2

        return ReviewResult(
            reviewer_id=self._config.id,
            name=self._config.name,
            score=score,
            passed=score >= self._config.threshold,
            reasoning=f"Deterministic scan found {finding_count} issue(s). LLM judgment unavailable.",
            suggestions=[f"Line {f.get('line', '?')}: {f.get('text', '')}" for f in all_findings[:10]],
            findings=all_findings,
        )

    def _parse_response(self, response_text: str) -> ReviewResult:
        """Parse structured JSON response from the LLM agent."""
        text = response_text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            first_nl = text.index("\n")
            text = text[first_nl + 1 :]
            if text.endswith("```"):
                text = text[:-3].rstrip()

        # Try to find JSON in the response
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start_idx = text.find("{")
            end_idx = text.rfind("}")
            if start_idx >= 0 and end_idx > start_idx:
                try:
                    data = json.loads(text[start_idx : end_idx + 1])
                except json.JSONDecodeError:
                    return self._fallback_result(response_text)
            else:
                return self._fallback_result(response_text)

        if not isinstance(data, dict):
            return self._fallback_result(response_text)

        score = int(data.get("score", 0))
        reasoning = str(data.get("reasoning", ""))
        suggestions_raw = data.get("suggestions", [])
        suggestions = [str(s) for s in suggestions_raw] if isinstance(suggestions_raw, list) else []
        findings_raw = data.get("findings", [])
        findings: list[dict[str, Any]] = [dict(f) for f in findings_raw] if isinstance(findings_raw, list) else []

        return ReviewResult(
            reviewer_id=self._config.id,
            name=self._config.name,
            score=score,
            passed=score >= self._config.threshold,
            reasoning=reasoning,
            suggestions=suggestions,
            findings=findings,
        )

    def _fallback_result(self, raw_response: str) -> ReviewResult:
        """Create a fallback result when response parsing fails."""
        return ReviewResult(
            reviewer_id=self._config.id,
            name=self._config.name,
            score=0,
            passed=False,
            reasoning=f"Failed to parse reviewer response. Raw: {raw_response[:200]}",
            suggestions=["Review agent returned unparseable response."],
            findings=[],
        )


# ---------------------------------------------------------------------------
# run_reviewer / run_all_sync — orchestration helpers
# ---------------------------------------------------------------------------


def run_reviewer(
    reviewer: ReviewerConfig,
    spec_content: str,
    model_config: dict[str, str],
) -> ReviewResult:
    """Create a ReviewerAgent and run it against spec content.

    Stdout/stderr are captured per-agent to prevent garbled output
    when multiple reviewers run concurrently.
    """
    agent = ReviewerAgent(config=reviewer, model_config=model_config)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        result = agent.review(spec_content)
    # Attach captured output for debugging without polluting the terminal
    return ReviewResult(
        reviewer_id=result.reviewer_id,
        name=result.name,
        score=result.score,
        passed=result.passed,
        reasoning=result.reasoning,
        suggestions=result.suggestions,
        findings=result.findings,
        debug_output=captured.getvalue(),
        elapsed_seconds=result.elapsed_seconds,
    )


def run_all_sync(
    spec_content: str,
    reviewers_dir: Path,
    *,
    model_config: dict[str, str] | None = None,
    threshold_overrides: dict[str, int] | None = None,
    max_workers: int = 10,
    rubric_filter: str | None = None,
) -> list[ReviewResult]:
    """Load all YAML reviewers and run them in parallel.

    Args:
        spec_content: The specification text to review.
        reviewers_dir: Directory containing reviewer YAML files.
        model_config: AWS/model configuration for Strands agents.
        threshold_overrides: Group-level threshold overrides.
        max_workers: Maximum parallel agents.
        rubric_filter: Optional group name to filter reviewers.

    Returns:
        Sorted list of ReviewResult instances.
    """
    total_start = time.monotonic()
    aws_config = model_config or {}
    reviewers = load_all_reviewers(reviewers_dir, threshold_overrides=threshold_overrides)

    if rubric_filter is not None:
        reviewers = [r for r in reviewers if r.group == rubric_filter]

    if not reviewers:
        return []

    logger.info(
        "Running %d reviewer(s) in parallel (max_workers=%d)",
        len(reviewers),
        max_workers,
    )
    results: list[ReviewResult] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for cfg in reviewers:
            future = executor.submit(run_reviewer, cfg, spec_content, aws_config)
            future_map[future] = cfg.id

        for future in as_completed(future_map):
            reviewer_id = future_map[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                logger.exception("Reviewer %s raised an exception", reviewer_id)
                error_msg = f"{type(exc).__name__}: {str(exc)[:300]}"
                results.append(
                    ReviewResult(
                        reviewer_id=reviewer_id,
                        name=reviewer_id,
                        score=0,
                        passed=False,
                        reasoning=f"AGENT ERROR: {error_msg}",
                        suggestions=[f"Fix the error and re-run: {error_msg}"],
                        findings=[],
                    )
                )

    total_elapsed = time.monotonic() - total_start
    results.sort(key=lambda r: r.reviewer_id)
    passed = sum(1 for r in results if r.passed)
    logger.info(
        "All %d reviewer(s) completed in %.1fs — %d passed, %d failed",
        len(results),
        total_elapsed,
        passed,
        len(results) - passed,
    )
    return results
