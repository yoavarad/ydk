# Subagent LLM handoff protocol

**Status:** accepted

YDK's LLM-backed steps (spec review, extraction, retrospectives, complexity scoring, compaction, AI code review and so on) used to call the Anthropic API directly, which needs an `ANTHROPIC_API_KEY`. YDK almost always runs inside an agent session that can already spawn subagents. We add a `subagent` provider: rather than calling a model, YDK writes the request to a file, stops, and lets the calling agent answer it with a subagent. The agent then re-runs the command, and YDK picks up the answer.

## Protocol

- **Request.** `LLMRequest` (`src/ydk/core/llm_provider.py`) holds `id`, `purpose`, `system`, `user`, `cacheable_context`, `output_schema` (the output model's `model_json_schema()`), `model_tier`, `model`, `agent` (a `subagent_type` hint) and `instructions`.
- **Content-addressed id.** `id` is the sha256 of the JSON array `[purpose, system, user, output_schema]` with sorted keys. The routing hints (`agent`, `model`, `model_tier`, `instructions`) are not part of the hash, so retuning which agent answers does not throw away existing answers.
- **Files.** Under `ai.subagent.dir` (default `.ydk/llm`): the request goes to `requests/<id>.json` and the agent writes the answer to `responses/<id>.json`. The answer must validate against `output_schema`.
- **Flow.** `SubagentProvider.invoke_structured(prompt, Model)` returns `Model.model_validate_json(response)` when the response file exists. When it does not, the provider writes the request file and raises `SubagentHandoff(request_paths)`. Plain `invoke(prompt)` uses the schema `{"text": str}`.
- **The handoff is a `BaseException`.** Many LLM call sites are fail-open (`except Exception`). `SubagentHandoff` derives from `BaseException`, like `KeyboardInterrupt`, so those blocks cannot swallow it. Only code that names it explicitly catches it.
- **Invalid responses fail loudly.** If a response cannot be read or does not validate, the provider raises `SubagentResponseError` with the file path. It never falls back to another provider and never silently re-requests.
- **Collect mode.** With `SubagentProvider(..., collect=True)`, each missing response raises `SubagentRequestPending` (a `SubagentHandoff` subclass) and the path is recorded. A fan-out caller catches that, carries on with the other items, then calls `flush()`, which raises a single `SubagentHandoff` with every pending path (each path once). `pending()` lists what has been recorded. If an uncaught `SubagentRequestPending` reaches a caller, it still behaves as a one-path handoff.

## Routing and config

```yaml
ai:
  provider: subagent          # global default
  routes:                     # per-purpose override of provider
    extract: anthropic
  subagent:
    dir: .ydk/llm
    agents:
      ai-code-review: {agent: code-reviewer, model: opus, instructions: "..."}
      default: {agent: general-purpose}
```

- `get_llm_provider(cfg, *, purpose=None, max_tokens=1024)` picks the provider from `ai.routes[purpose]`, falling back to `ai.provider`.
- The model tier depends on the purpose. `spec-review`, `ai-code-review`, `spec-alignment` and `retrospective` use `review`. `layer-b-scan`, `extract`, `complexity`, `compaction`, `contradiction`, `checkpoint`, any unknown purpose and no purpose at all use `fast`. Calls that pass no purpose therefore keep the previous hard-coded `fast` tier.
- The agent hints come from `ai.subagent.agents[purpose]`, then `agents.default`, then the built-in `general-purpose` with no model override. When the agent sets no `model`, the request's `model` is `ai.model_for(tier)`.

## Default provider decision

- `ydk init` (through `init_config`) writes `ai: {provider: subagent}`, so new repos default to the subagent provider.
- `AIConfig.provider` still defaults to `anthropic`. Existing configs without `ai.provider`, and repos with no config file, keep the Anthropic behaviour they have today. Moving an existing repo to subagents is a one-line opt-in.
- We rejected flipping the model default, because every existing repo would silently stop calling the API and start emitting handoffs that its tooling cannot yet act on.

## Consequences

- The provider core is all in this change. Wiring callers to pass `purpose` and having CLI commands turn `SubagentHandoff` into a dedicated exit code with a printed request block are follow-up tasks in story #616. Until those land, a new repo that runs an LLM-backed command gets an uncaught `SubagentHandoff`.
- A relative `ai.subagent.dir` resolves against the process cwd, in the same way as the other `.ydk/` paths in config.
- `invoke_structured` has no system-prompt argument, so `system` is `""` and `cacheable_context` is `None` for now. Both fields are in the request model so callers that split their prompts can fill them later.
- `responses/` acts as a durable cache. An identical prompt and schema reuse the stored answer, and any change to either produces a new id and a new request.
