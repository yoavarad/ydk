"""Canonical LLM provider abstraction: Anthropic-backed and subagent-handoff implementations."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast, runtime_checkable

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from ydk.models.config import YdkConfig

_ModelT = TypeVar("_ModelT", bound=BaseModel)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers used across YDK's core modules."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to an LLM and return the text response."""
        ...


@runtime_checkable
class StructuredLLMProvider(LLMProvider, Protocol):
    """An LLMProvider that can also return schema-validated structured output."""

    def invoke_structured(
        self,
        prompt: str,
        output_format: type[_ModelT],
        *,
        system: str = "",
        cacheable_context: str | None = None,
    ) -> _ModelT:
        """Send a prompt and return the response parsed into ``output_format``.

        ``system`` is the instruction prompt; ``cacheable_context`` is a large
        shared prefix (e.g. a spec) that providers may cache across calls.
        """
        ...


class AnthropicLLMProvider:
    """LLMProvider implementation backed by the Anthropic SDK."""

    def __init__(self, client: object, model_id: str, max_tokens: int = 1024) -> None:
        self._client: Any = client
        self._model_id = model_id
        self._max_tokens = max_tokens

    def invoke(self, prompt: str) -> str:
        """Send a prompt to Claude and return the first text block's content.

        Raises ``ClaudeAPIError`` on API failures or truncated output.
        """
        from ydk.core.claude_client import create_message

        response = create_message(
            self._client,
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "text":
                return cast("Any", block).text
        return ""

    def invoke_structured(
        self,
        prompt: str,
        output_format: type[_ModelT],
        *,
        system: str = "",
        cacheable_context: str | None = None,
    ) -> _ModelT:
        """Send a prompt to Claude and return its structured output as ``output_format``.

        ``cacheable_context`` becomes a system block marked ``cache_control:
        ephemeral`` so repeated calls sharing it hit the prompt cache.
        Raises ``ClaudeAPIError`` on API failures, truncated output, or a
        response without structured output.
        """
        from ydk.core.claude_client import parse_message

        kwargs: dict[str, Any] = {}
        system_blocks: list[dict[str, Any]] = []
        if system:
            system_blocks.append({"type": "text", "text": system})
        if cacheable_context is not None:
            system_blocks.append({"type": "text", "text": cacheable_context, "cache_control": {"type": "ephemeral"}})
        if system_blocks:
            kwargs["system"] = system_blocks
        return parse_message(
            self._client,
            output_format,
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )


class LLMRequest(BaseModel):
    """One LLM call handed off to a subagent, keyed by a content hash (see ADR 0004)."""

    id: str
    purpose: str
    system: str
    user: str
    cacheable_context: str | None = None
    output_schema: dict[str, Any]
    model_tier: str
    model: str
    agent: str
    instructions: str = ""

    @staticmethod
    def compute_id(
        *,
        purpose: str,
        system: str,
        user: str,
        output_schema: dict[str, Any],
        cacheable_context: str | None = None,
    ) -> str:
        """Return the sha256 of the prompt content; routing hints do not affect it.

        ``cacheable_context`` is hashed only when set, so ids of requests
        without it are unchanged.
        """
        content: list[Any] = [purpose, system, user, output_schema]
        if cacheable_context is not None:
            content.append(cacheable_context)
        payload = json.dumps(content, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        *,
        purpose: str,
        system: str,
        user: str,
        output_schema: dict[str, Any],
        model_tier: str,
        model: str,
        agent: str,
        instructions: str = "",
        cacheable_context: str | None = None,
    ) -> LLMRequest:
        """Construct a request with its content-hash ``id`` filled in."""
        return cls(
            id=cls.compute_id(
                purpose=purpose,
                system=system,
                user=user,
                output_schema=output_schema,
                cacheable_context=cacheable_context,
            ),
            purpose=purpose,
            system=system,
            user=user,
            cacheable_context=cacheable_context,
            output_schema=output_schema,
            model_tier=model_tier,
            model=model,
            agent=agent,
            instructions=instructions,
        )


class SubagentHandoff(BaseException):
    """Raised when LLM work must be done by a subagent; carries the request file paths.

    Derives from ``BaseException`` (like ``KeyboardInterrupt``) so the many
    fail-open ``except Exception`` blocks around LLM calls cannot swallow it.
    """

    def __init__(self, request_paths: list[Path]) -> None:
        self.request_paths = list(request_paths)
        listed = "\n".join(f"  {p}" for p in self.request_paths)
        super().__init__(f"subagent handoff: {len(self.request_paths)} request(s) pending\n{listed}")


class SubagentRequestPending(SubagentHandoff):
    """Raised per call in collect mode; ``SubagentProvider.flush`` raises the batched handoff."""


class SubagentResponseError(ValueError):
    """A subagent response file exists but cannot be read or does not match the output schema."""


class _TextResponse(BaseModel):
    text: str


class SubagentProvider:
    """StructuredLLMProvider that exchanges JSON files with a calling agent's subagents.

    Requests go to ``<root>/requests/<id>.json``; answers are read from
    ``<root>/responses/<id>.json``. With ``collect=True`` each missing response
    raises ``SubagentRequestPending`` and is recorded, so a fan-out caller can
    continue and later ``flush()`` one ``SubagentHandoff`` for all of them.
    """

    def __init__(
        self,
        root: Path,
        *,
        purpose: str,
        model_tier: str,
        model: str,
        agent: str,
        instructions: str = "",
        collect: bool = False,
    ) -> None:
        self._root = Path(root)
        self._purpose = purpose
        self._model_tier = model_tier
        self._model = model
        self._agent = agent
        self._instructions = instructions
        self._collect = collect
        self._pending: list[Path] = []

    def invoke(self, prompt: str) -> str:
        """Return the subagent's text answer (response schema ``{"text": str}``)."""
        return self.invoke_structured(prompt, _TextResponse).text

    def invoke_structured(
        self,
        prompt: str,
        output_format: type[_ModelT],
        *,
        system: str = "",
        cacheable_context: str | None = None,
    ) -> _ModelT:
        """Return the validated response, or write the request and raise a handoff."""
        request = LLMRequest.build(
            purpose=self._purpose,
            system=system,
            user=prompt,
            cacheable_context=cacheable_context,
            output_schema=output_format.model_json_schema(),
            model_tier=self._model_tier,
            model=self._model,
            agent=self._agent,
            instructions=self._instructions,
        )
        response_path = self._root / "responses" / f"{request.id}.json"
        if response_path.is_file():
            try:
                return output_format.model_validate_json(response_path.read_text(encoding="utf-8"))
            except (ValidationError, OSError, UnicodeDecodeError) as exc:
                msg = f"invalid subagent response {response_path}: {exc}"
                raise SubagentResponseError(msg) from exc

        request_path = self._root / "requests" / f"{request.id}.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        if request_path not in self._pending:
            self._pending.append(request_path)
        if self._collect:
            raise SubagentRequestPending([request_path])
        raise SubagentHandoff([request_path])

    def pending(self) -> list[Path]:
        """Return request paths recorded since the last ``flush``."""
        return list(self._pending)

    def flush(self) -> None:
        """Raise one ``SubagentHandoff`` for all pending requests and clear them; no-op if none."""
        if not self._pending:
            return
        paths, self._pending = self._pending, []
        raise SubagentHandoff(paths)


class ClaudeCliError(RuntimeError):
    """The ``claude`` CLI is missing, failed, or returned unusable output."""


class ClaudeCliProvider:
    """StructuredLLMProvider that shells out to headless ``claude -p`` (no parent agent needed)."""

    def __init__(self, model_id: str | None = None, *, binary: str = "claude", timeout: float = 300.0) -> None:
        self._model_id = model_id
        self._binary = binary
        self._timeout = timeout

    def _run(self, prompt: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        resolved = shutil.which(self._binary)
        if resolved is None:
            msg = f"`{self._binary}` not found on PATH; install Claude Code or choose another ai.provider"
            raise ClaudeCliError(msg)
        cmd = [resolved, "-p", "--output-format", "json"]
        if self._model_id:
            cmd += ["--model", self._model_id]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            msg = f"`{self._binary}` not found on PATH; install Claude Code or choose another ai.provider"
            raise ClaudeCliError(msg) from exc
        except subprocess.TimeoutExpired as exc:
            msg = f"`{self._binary}` timed out after {self._timeout}s"
            raise ClaudeCliError(msg) from exc
        if proc.returncode != 0:
            msg = f"`{self._binary}` exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}"
            raise ClaudeCliError(msg)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            msg = f"`{self._binary}` returned non-JSON output: {exc}"
            raise ClaudeCliError(msg) from exc
        if not isinstance(data, dict):
            msg = f"`{self._binary}` returned unexpected JSON shape"
            raise ClaudeCliError(msg)
        return cast("dict[str, Any]", data)

    def invoke(self, prompt: str) -> str:
        """Return the CLI's text result."""
        return str(self._run(prompt, None).get("result", ""))

    def invoke_structured(
        self,
        prompt: str,
        output_format: type[_ModelT],
        *,
        system: str = "",
        cacheable_context: str | None = None,
    ) -> _ModelT:
        """Return the CLI output validated into ``output_format``; system and context precede the prompt."""
        full_prompt = "\n\n".join(part for part in (system, cacheable_context, prompt) if part)
        data = self._run(full_prompt, output_format.model_json_schema())
        try:
            structured = data.get("structured_output")
            if structured is not None:
                return output_format.model_validate(structured)
            return output_format.model_validate_json(str(data.get("result", "")))
        except ValidationError as exc:
            msg = f"`{self._binary}` output does not match {output_format.__name__}: {exc}"
            raise ClaudeCliError(msg) from exc


_PURPOSE_TIERS: dict[str, str] = {
    "spec-review": "review",
    "ai-code-review": "review",
    "spec-alignment": "review",
    "retrospective": "review",
    "layer-b-scan": "fast",
    "extract": "fast",
    "complexity": "fast",
    "compaction": "fast",
    "contradiction": "fast",
    "checkpoint": "fast",
}


def tier_for_purpose(purpose: str | None) -> str:
    """Return the model tier for ``purpose``; unknown or missing purposes use ``fast``."""
    return _PURPOSE_TIERS.get(purpose or "", "fast")


def _build_anthropic_provider(cfg: YdkConfig, max_tokens: int, purpose: str | None, tier: str) -> StructuredLLMProvider:
    del purpose
    from ydk.core.claude_client import build_client

    client = build_client(cfg.anthropic.api_key_env)
    model_id = cfg.ai.model_for(tier)
    return AnthropicLLMProvider(client=client, model_id=model_id, max_tokens=max_tokens)


def _build_subagent_provider(cfg: YdkConfig, max_tokens: int, purpose: str | None, tier: str) -> StructuredLLMProvider:
    del max_tokens  # the subagent owns its own output budget
    agent = cfg.ai.subagent.agent_for(purpose)
    return SubagentProvider(
        Path(cfg.ai.subagent.dir),
        purpose=purpose or "default",
        model_tier=tier,
        model=agent.model or cfg.ai.model_for(tier),
        agent=agent.agent,
        instructions=agent.instructions,
    )


def _build_claude_cli_provider(
    cfg: YdkConfig, max_tokens: int, purpose: str | None, tier: str
) -> StructuredLLMProvider:
    del max_tokens, purpose  # the CLI owns its own output budget
    return ClaudeCliProvider(cfg.ai.model_for(tier))


_PROVIDER_BUILDERS = {
    "claude-cli": _build_claude_cli_provider,
    "anthropic": _build_anthropic_provider,
    "subagent": _build_subagent_provider,
}


def get_llm_provider(
    cfg: YdkConfig, *, purpose: str | None = None, max_tokens: int = 1024, tier: str | None = None
) -> StructuredLLMProvider | None:
    """Construct an LLMProvider for ``purpose`` from a YdkConfig.

    The provider is ``cfg.ai.routes[purpose]`` if set, else ``cfg.ai.provider``;
    the model tier is ``tier`` when given, else follows the purpose (``fast``
    when unknown or omitted).
    Returns ``None`` for an unknown provider or an unexpected construction
    error. Missing credentials are not swallowed: ``MissingCredentialsError``
    propagates so callers can report it before any request is made.
    """
    from ydk.core.claude_client import ClaudeAPIError

    try:
        builder = _PROVIDER_BUILDERS.get(cfg.ai.provider_for(purpose))
        if builder is None:
            return None
        return builder(cfg, max_tokens, purpose, tier or tier_for_purpose(purpose))
    except ClaudeAPIError:
        raise
    except Exception:
        return None
