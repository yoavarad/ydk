"""YAML-based reviewer definitions for spec verification.

Each reviewer criterion is defined by a YAML file containing:
- Inline Python tool code (compiled at load time via ``exec()``)
- A detailed system prompt
- Threshold, scoring and model-tier metadata

Reviewers are executed by ``ydk.core.reviewer_engine.ReviewerEngine``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

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
    model_tier: str = "review"


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
        model_tier=raw.get("model_tier", "review"),
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
