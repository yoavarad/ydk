"""Pydantic models for .ydk/config.yaml."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Single source of truth for Claude model IDs. Every LLM call site resolves its
# model through ``AIConfig.model_for(tier)``; upgrading a model is a one-line change here
# (or a per-project override under ``ai.model_tiers`` in .ydk/config.yaml).
DEFAULT_MODEL_TIERS: dict[str, str] = {
    "fast": "claude-haiku-4-5",
    "review": "claude-sonnet-5",
    "deep": "claude-opus-5-5",
}


def _drop_legacy_keys(data: object, *keys: str) -> object:
    """Drop removed config keys so older .ydk/config.yaml files still validate."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k not in keys}
    return data


class ProjectConfig(BaseModel):
    """Core project metadata and paths."""

    model_config = ConfigDict(extra="forbid")

    name: str
    spec_location: str = "docs/specs"
    adrs_location: str = "docs/adrs"
    research_location: str = "docs/research"
    remote: Literal["local", "github", "gitlab"] = "local"
    stack: str = ""


class PrePushHooks(BaseModel):
    """Flags controlling which pre-push enforcement checks are active."""

    model_config = ConfigDict(extra="forbid")

    spec_check: bool = False
    task_check: bool = False


class HooksConfig(BaseModel):
    """Git-hook integration settings."""

    model_config = ConfigDict(extra="forbid")

    pre_push: PrePushHooks = PrePushHooks()
    commit_msg_check: bool = True


class SpecCheckThresholds(BaseModel):
    """Minimum scores each spec-check criterion must reach to pass."""

    model_config = ConfigDict(extra="forbid")

    completeness: int = Field(default=8, ge=0, le=10)
    clarity: int = Field(default=8, ge=0, le=10)
    architecture: int = Field(default=8, ge=0, le=10)
    quality: int = Field(default=7, ge=0, le=10)


class CustomCriterion(BaseModel):
    """User-defined evaluation criterion for spec-check."""

    model_config = ConfigDict(extra="forbid")

    id: str
    rubric: str
    name: str
    prompt: str
    threshold: int = Field(ge=0, le=10)


class SpecCheckConfig(BaseModel):
    """Settings for the AI-powered specification checker."""

    model_config = ConfigDict(extra="forbid")

    timeout: int = 60
    global_timeout: int = 120
    concurrency: int = 10
    results_path: str = ".ydk/spec-check-results.json"
    thresholds: SpecCheckThresholds = SpecCheckThresholds()
    custom: list[CustomCriterion] = Field(default_factory=list)
    reviewers_path: str = ".ydk/spec-reviewers"

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_model(cls, data: object) -> object:
        # ``spec_check.model`` was replaced by the ``review`` model tier.
        return _drop_legacy_keys(data, "model")


class TaskManagementConfig(BaseModel):
    """Feature flags for task-management enforcement."""

    model_config = ConfigDict(extra="forbid")

    dag_validation: bool = True
    coverage_check: bool = True
    coverage_exclude: list[str] = Field(default_factory=list)


class ExecutionConfig(BaseModel):
    """Limits for parallel agent execution."""

    model_config = ConfigDict(extra="forbid")

    max_parallel_agents: int = 5
    task_timeout_minutes: int = 30
    worktree_isolation: bool = True


class AIConfig(BaseModel):
    """AI model tier configuration for cached fan-out reviewer engine."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "anthropic"
    model_tiers: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODEL_TIERS))

    def model_for(self, tier: str) -> str:
        """Return the model ID for ``tier``, falling back to the built-in default tier."""
        model_id = self.model_tiers.get(tier) or DEFAULT_MODEL_TIERS.get(tier)
        if not model_id:
            msg = f"unknown model tier {tier!r} (known: {sorted(DEFAULT_MODEL_TIERS)})"
            raise ValueError(msg)
        return model_id


class AnthropicConfig(BaseModel):
    """Anthropic API credential settings."""

    model_config = ConfigDict(extra="forbid")

    api_key_env: str = "ANTHROPIC_API_KEY"


class MemoryConfig(BaseModel):
    """Vector-memory subsystem configuration."""

    model_config = ConfigDict(extra="forbid")

    # Not currently read: the local embedding backend (chromadb's
    # DefaultEmbeddingFunction) hardcodes MiniLM-L6 and has no model-name override.
    embedding_model: str = "all-MiniLM-L6-v2"
    auto_bootstrap: bool = True
    chroma_path: str = ".ydk/memory/chroma"

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_auto_extract(cls, data: object) -> object:
        # ``memory.auto_extract`` was removed; use ``ydk memory extract`` explicitly.
        return _drop_legacy_keys(data, "auto_extract")


class LearningConfig(BaseModel):
    """Compound-learning process settings."""

    model_config = ConfigDict(extra="forbid")

    require_epic_retro: bool = True


class VerificationFilterConfig(BaseModel):
    """Whitelist filter for which verification checks to run."""

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=list)


class ComponentConfig(BaseModel):
    """Component manifest system paths."""

    model_config = ConfigDict(extra="forbid")

    schemas_path: str = ".ydk/schemas"
    components_path: str = ".ydk/components"


class YdkConfig(BaseModel):
    """Top-level YDK configuration aggregating all sub-configs."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig
    hooks: HooksConfig = HooksConfig()
    spec_check: SpecCheckConfig = SpecCheckConfig()
    task_management: TaskManagementConfig = TaskManagementConfig()
    execution: ExecutionConfig = ExecutionConfig()
    ai: AIConfig = AIConfig()
    anthropic: AnthropicConfig = AnthropicConfig()
    memory: MemoryConfig = MemoryConfig()
    learning: LearningConfig = LearningConfig()
    verification: VerificationFilterConfig = VerificationFilterConfig()
    components: ComponentConfig = ComponentConfig()
