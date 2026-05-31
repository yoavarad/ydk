"""Models for procedural memory — prompt outcome tracking and reporting."""

from pydantic import BaseModel, ConfigDict, Field


class PromptOutcome(BaseModel):
    """A single recorded outcome for a prompt execution."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    input_hash: str
    success: bool
    feedback: str | None = None
    timestamp: str = ""


class ProceduralReport(BaseModel):
    """Summary report of prompt effectiveness across all tracked prompts."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    total_executions: int
    successes: int
    failures: int
    effectiveness: float = Field(ge=0.0, le=1.0)
    suggestion: str | None = None
