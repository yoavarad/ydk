"""Pydantic models for .odk/config.yaml."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    model: str = "us.anthropic.claude-sonnet-4-6"
    timeout: int = 60
    global_timeout: int = 120
    concurrency: int = 10
    results_path: str = ".odk/spec-check-results.json"
    thresholds: SpecCheckThresholds = SpecCheckThresholds()
    custom: list[CustomCriterion] = Field(default_factory=list)
    reviewers_path: str = ".odk/spec-reviewers"


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

    provider: str = "bedrock"
    model_tiers: dict[str, str] = {
        "smart": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "fast": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "reasoning": "us.anthropic.claude-opus-4-6-v1",
    }


class AwsConfig(BaseModel):
    """AWS credential and region settings."""

    model_config = ConfigDict(extra="forbid")

    profile: str = ""  # AWS profile name. Empty = use default credentials
    region: str = "us-east-1"


class MemoryConfig(BaseModel):
    """Vector-memory subsystem configuration."""

    model_config = ConfigDict(extra="forbid")

    embedding_model: str = "amazon.titan-embed-text-v2:0"
    auto_bootstrap: bool = True
    auto_extract: bool = True
    chroma_path: str = ".odk/memory/chroma"


class VerificationFilterConfig(BaseModel):
    """Whitelist filter for which verification checks to run."""

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=list)


class ComponentConfig(BaseModel):
    """Component manifest system paths."""

    model_config = ConfigDict(extra="forbid")

    schemas_path: str = ".odk/schemas"
    components_path: str = ".odk/components"


class OdkConfig(BaseModel):
    """Top-level ODK configuration aggregating all sub-configs."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig
    hooks: HooksConfig = HooksConfig()
    spec_check: SpecCheckConfig = SpecCheckConfig()
    task_management: TaskManagementConfig = TaskManagementConfig()
    execution: ExecutionConfig = ExecutionConfig()
    ai: AIConfig = AIConfig()
    aws: AwsConfig = AwsConfig()
    memory: MemoryConfig = MemoryConfig()
    verification: VerificationFilterConfig = VerificationFilterConfig()
    components: ComponentConfig = ComponentConfig()
