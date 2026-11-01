"""LLM calls for the AI verification plugins (ai-code-review, spec-alignment).

Routes each call through ``get_llm_provider`` for the plugin's purpose. With the
subagent provider (ADR 0004) a plugin can only be answered when an agent drives
the run, i.e. inside ``ydk task done``, which sets ``llm_handoff`` in the plugin
context. Elsewhere (git pre-push, plain ``ydk verify run``) the plugin reports a skip.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ydk.models.config import AIConfig, AnthropicConfig, ProjectConfig, YdkConfig
from ydk.models.verification import NEEDS_LLM

LLM_HANDOFF_KEY = "llm_handoff"

_CREDENTIAL_HINT = (
    " Set up credentials via the `ydk init` instructions, or disable this plugin by removing it "
    "from `verification.enabled` in .ydk/config.yaml if it is intentionally unused."
)


def plugin_config(context: dict[str, Any]) -> YdkConfig:
    """Rebuild the AI and Anthropic settings a plugin needs from its verification context.

    A relative ``ai.subagent.dir`` is resolved against ``project_root`` so request
    paths do not depend on the plugin process's cwd.
    """
    config = context.get("config") or {}
    ai = AIConfig.model_validate(config.get("ai") or {})
    subagent_dir = Path(ai.subagent.dir)
    if not subagent_dir.is_absolute():
        resolved = str(Path(context["project_root"]) / subagent_dir)
        ai = ai.model_copy(update={"subagent": ai.subagent.model_copy(update={"dir": resolved})})
    anthropic = AnthropicConfig.model_validate(config.get("anthropic") or {})
    return YdkConfig(project=ProjectConfig(name="verification"), ai=ai, anthropic=anthropic)


def run_plugin_llm[ModelT: BaseModel](
    context: dict[str, Any],
    *,
    name: str,
    purpose: str,
    prompt: str,
    output_format: type[ModelT],
    kind: str,
    start: float,
    max_tokens: int = 8192,
) -> ModelT | dict[str, Any]:
    """Return the provider's ``output_format`` answer, or the plugin result to emit instead.

    The returned result dict is a SKIPPED pass (subagent provider outside task done),
    a ``NEEDS_LLM`` failure carrying ``request_paths`` (subagent provider inside task
    done, response not written yet), or an uncached failure for credential, provider,
    API and schema errors. *kind* names the output in the malformed-output message.
    """
    from ydk.core.claude_client import ClaudeAPIError, MissingCredentialsError
    from ydk.core.llm_provider import ClaudeCliError, SubagentHandoff, SubagentResponseError, get_llm_provider

    def result(passed: bool, output: str, **detail: object) -> dict[str, Any]:
        return {
            "name": name,
            "passed": passed,
            "output": output,
            "duration_seconds": round(time.time() - start, 1),
            "detail": {**detail, "no_cache": True},
        }

    cfg = plugin_config(context)
    provider_name = cfg.ai.provider_for(purpose)
    if provider_name == "subagent" and not context.get(LLM_HANDOFF_KEY):
        reason = f"ai.provider routes {purpose} to subagent, which is answered only inside `ydk task done`"
        return result(True, f"Skipped: {reason}", status="SKIPPED", skip_reason=reason)

    try:
        provider = get_llm_provider(cfg, purpose=purpose, max_tokens=max_tokens)
    except MissingCredentialsError as exc:
        return result(False, f"{exc}{_CREDENTIAL_HINT}", credential_error=True)
    if provider is None:
        return result(False, f"ERROR: could not build ai.provider {provider_name!r} for {purpose}", error=True)

    try:
        return provider.invoke_structured(prompt, output_format)
    except SubagentHandoff as handoff:
        paths = [str(p) for p in handoff.request_paths]
        listed = "\n".join(f"  {p}" for p in paths)
        return result(False, f"Waiting on subagent LLM response(s):\n{listed}", status=NEEDS_LLM, request_paths=paths)
    except ValidationError as exc:
        return result(False, f"ERROR: malformed {kind} from model: {exc}", error=True, malformed=True)
    except (ClaudeAPIError, ClaudeCliError, SubagentResponseError) as exc:
        return result(False, f"ERROR: {exc}", error=True)
