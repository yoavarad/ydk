"""Shared ``pr-body-validation`` plugin invocation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from ydk.core.config import load_config
from ydk.core.verifier import Verifier
from ydk.models.config import PrBodyConfig

if TYPE_CHECKING:
    from pathlib import Path

    from ydk.models.verification import CheckResult


def run_pr_body_validation(
    pr_body: str,
    changed_files: list[str],
    project_root: Path,
    *,
    verifier: Verifier | None = None,
    context: dict[str, object] | None = None,
) -> CheckResult | None:
    """Run the ``pr-body-validation`` plugin by name against *pr_body*.

    Returns ``None`` when the plugin is not installed. *context* seeds the
    plugin context; ``pr_body`` is always taken from the explicit argument,
    and ``changed_files`` too unless it is empty and *context* already has one.
    """
    v = verifier or Verifier(project_root=project_root, use_cache=False)
    matched = v.filter_by_name(v.discover_plugins(), "pr-body-validation")
    if not matched:
        return None

    plugin_context: dict[str, object] = dict(context) if context else {"project_root": str(project_root.resolve())}
    plugin_context["pr_body"] = pr_body
    try:
        ui_exclude = load_config(project_root / ".ydk" / "config.yaml").verification.pr_body.ui_exclude
    except (ValidationError, yaml.YAMLError):
        ui_exclude = PrBodyConfig().ui_exclude
    plugin_context["ui_exclude"] = list(ui_exclude)
    if changed_files or "changed_files" not in plugin_context:
        plugin_context["changed_files"] = changed_files
    results = asyncio.run(v.run_layer(matched, plugin_context))
    return results[0] if results else None
