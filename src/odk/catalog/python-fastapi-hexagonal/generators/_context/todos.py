"""TODO marker generation for ODK generator stubs."""

from __future__ import annotations

import textwrap


def _wrap_comment(text: str, indent: str = "    # ") -> str:
    """Wrap comment text so each line fits within 119 chars including the indent prefix."""
    width = 119 - len(indent)
    lines = textwrap.wrap(text, width=width)
    if not lines:
        return f"{indent}{text}"
    return "\n".join(f"{indent}{line}" for line in lines)


def _extract_return_type(method_def: dict) -> str:
    """Extract the return type string from a method definition."""
    returns = method_def.get("returns", "None")
    if isinstance(returns, dict):
        return returns.get("type", "None")
    return str(returns)


def service_todo(
    service_name: str, method_name: str, method_def: dict, artifact_ref: str = "services.yaml"
) -> list[str]:
    """
    Generate structured TODO comment lines for a service method stub.
    Accepts ODK contract format: method_name + method_def dict.
    Returns a list of comment lines (without the # prefix — template adds that).

    Reads 'input' (not 'args'/'params'), 'output' (not 'returns'),
    and 'errors' (not 'raises').
    """
    input_fields = method_def.get("input", {})
    if isinstance(input_fields, dict):
        params_str = ", ".join(f"{k}({v})" for k, v in input_fields.items())
    else:
        params_str = str(input_fields)

    errors = method_def.get("errors", [])
    error_names = [e["name"] if isinstance(e, dict) else str(e) for e in (errors or [])]
    error_str = ", ".join(error_names) if error_names else "(none)"

    description = method_def.get("description", f"Add implementation for {method_name}")
    desc_prefix = "    # IMPLEMENT: "
    desc_wrapped = _wrap_comment(description, indent=desc_prefix)
    desc_lines = desc_wrapped.split("\n")

    lines = [
        f"# ODK-TODO: {service_name}.{method_name}",
        *desc_lines,
        f"# SPEC: {artifact_ref} → {service_name}.{method_name}",
        (f"#   Input: {params_str[:80]}..." if len(params_str) > 80 else f"#   Input: {params_str}")
        if params_str
        else "#   Input: (none)",
        f"#   Output: {str(method_def.get('output', 'None'))[:80]}",
        f"#   Errors: {error_str}",
    ]
    return lines


def adapter_todo(
    adapter_name: str, method_name: str, adapter_spec: dict, artifact_ref: str = "adapters.yaml"
) -> list[str]:
    """
    Generate structured TODO comment lines for an adapter method stub.
    Uses the adapter's todo: field from adapters.yaml if present.
    Handles __init__ specially — no method args, just initialization context.
    """
    technology = adapter_spec.get("technology", "external API")
    implements = adapter_spec.get("implements", "?")
    reference = adapter_spec.get("reference", "")

    if method_name == "__init__":
        if technology.lower() in ("apscheduler", "apscheduler-async"):
            lines = [
                f"# ODK-TODO: {adapter_name}",
                "# IMPLEMENT: Initialize AsyncIOScheduler — do NOT start it here.",
                "# LIFECYCLE: call self._scheduler.start() in app/main.py lifespan startup",
                "# LIFECYCLE: call self._scheduler.shutdown() in lifespan teardown",
                f"# SPEC: {artifact_ref} → {adapter_name} (implements: {implements})",
                f"#   Technology: {technology}  (AsyncIOScheduler from apscheduler.schedulers.asyncio)",
                "#   Required env vars: see .env.example",
            ]
            if reference:
                lines.append(f"#   Reference: {reference}")
            return lines
        lines = [
            f"# ODK-TODO: {adapter_name}.__init__",
            f"# IMPLEMENT: Initialize {technology} SDK client, configure from env vars",
            f"# SPEC: {artifact_ref} → {adapter_name} (implements: {implements})",
            f"#   Technology: {technology}",
            "#   Required env vars: see .env.example",
        ]
        if reference:
            lines.append(f"#   Reference: {reference}")
        return lines

    todo_text = adapter_spec.get("todo", f"Implement {method_name} using {technology}")

    lines = [
        f"# ODK-TODO: {adapter_name}.{method_name}",
        f"# IMPLEMENT: {adapter_name}.{method_name}",
        f"# SPEC: {artifact_ref} → {adapter_name} (implements: {implements})",
        f"#   Technology: {technology}",
    ]
    if todo_text:
        todo_indent = "#   "
        for raw_line in todo_text.strip().split("\n"):
            stripped = raw_line.strip()
            if not stripped:
                continue
            wrapped = _wrap_comment(stripped, indent=todo_indent)
            lines.extend(wrapped.split("\n"))
    if reference:
        lines.append(f"#   Reference: {reference}")
    return lines


def test_todo(
    test_type: str,
    subject: str,
    method_name: str | None = None,
    method_def: dict | None = None,
    artifact_ref: str = "services.yaml",
) -> list[str]:
    """Generate TODO comment lines for a test stub."""
    desc = f"Test {subject}"
    if method_name:
        desc = f"Test {subject}.{method_name}"
        if method_def:
            params = method_def.get("params", {}) or method_def.get("input", {})
            input_summary = str(params) if params else "(none)"
            returns = method_def.get("returns", {})
            output = returns.get("type", "?") if isinstance(returns, dict) else str(returns)
        else:
            input_summary = "(none)"
            output = "?"
        return [
            f"# ODK-TODO: test {subject}.{method_name}",
            f"# IMPLEMENT: Write test assertions for {desc}",
            f"#   Input: {input_summary}",
            f"#   Output: {output}",
        ]
    return [
        f"# ODK-TODO: test {test_type}:{subject}",
        f"# IMPLEMENT: {desc}",
    ]
