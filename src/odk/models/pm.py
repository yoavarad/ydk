"""Project-management models shared across all repository backends.

STUB: Minimal definitions for GitLab/GitHub repository imports.
The other agent may expand these — do not duplicate logic here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from odk.models.gate import Gate  # noqa: TC001


class DependencyType(StrEnum):
    """Relationship type between two tasks."""

    BLOCKS = "blocks"
    VALIDATES = "validates"
    CAUSED_BY = "caused-by"
    CONDITIONAL_BLOCKS = "conditional-blocks"
    WAITS_FOR = "waits-for"
    DISCOVERED_FROM = "discovered-from"
    SUPERSEDES = "supersedes"
    RELATED = "related"


# Types that create execution edges in the DAG.
BLOCKING_DEPENDENCY_TYPES: frozenset[DependencyType] = frozenset(
    {
        DependencyType.BLOCKS,
        DependencyType.CONDITIONAL_BLOCKS,
        DependencyType.WAITS_FOR,
    }
)


class Dependency(BaseModel):
    """A typed dependency link to another task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    type: DependencyType = DependencyType.BLOCKS


class TaskStatus(StrEnum):
    """Issue lifecycle states (backend-agnostic)."""

    OPEN = "open"
    IN_PROGRESS = "in-progress"
    BLOCKED_BY_CODE = "blocked-by-code"
    BLOCKED_BY_DECISION = "blocked-by-decision"
    IN_REVIEW = "in-review"
    DONE = "done"
    CLOSED = "closed"


class AcceptanceCriterion(BaseModel):
    """A single acceptance criterion with completion tracking."""

    model_config = ConfigDict(extra="forbid")

    text: str
    done: bool = False


class DependencyStatus(BaseModel):
    """Status of a single dependency link."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    title: str
    resolved: bool = False


class TaskCreate(BaseModel):
    """Payload for creating a new task issue."""

    model_config = ConfigDict(extra="forbid")

    title: str
    story_id: str | None = None
    component_refs: list[str] = Field(default_factory=list)
    spec_refs: list[str] = Field(default_factory=list)
    component_refs: list[str] = Field(default_factory=list)
    dependencies: list[str | Dependency] = Field(default_factory=list)
    test_strategy: str = ""
    description: str = ""
    acceptance_criteria: list[str | AcceptanceCriterion] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    milestone: str | None = None
    complexity: int | None = None
    gates: list[Gate] = Field(default_factory=list)


class TaskDetail(BaseModel):
    """Full task representation — used by both remote and local repos."""

    model_config = ConfigDict(extra="forbid")

    # Remote repos use ``number``; local repos use ``id``.
    number: int = 0
    id: str = ""
    title: str
    story_id: str | None = None
    spec_refs: list[str] = Field(default_factory=list)
    component_refs: list[str] = Field(default_factory=list)
    dependencies: list[str | Dependency] = Field(default_factory=list)
    test_strategy: str = ""
    description: str = ""
    acceptance_criteria: list[str | AcceptanceCriterion] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    status: str = "open"
    assignee: str | None = None
    session_id: str | None = None
    complexity: int | None = None
    complexity_reasoning: str | None = None
    url: str = ""
    gates: list[Gate] = Field(default_factory=list)


class TaskSummary(BaseModel):
    """Lightweight task info returned by manifest-based listing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: str = "open"
    dependencies_met: bool = True
    dependents_count: int = 0


class StoryCreate(BaseModel):
    """Payload for creating a story issue."""

    model_config = ConfigDict(extra="forbid")

    title: str
    epic_id: str | None = None
    spec_refs: list[str] = Field(default_factory=list)
    component_refs: list[str] = Field(default_factory=list)
    description: str = ""
    acceptance_criteria: list[str | AcceptanceCriterion] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    milestone: str | None = None


class StoryDetail(BaseModel):
    """Full story read back from the remote."""

    model_config = ConfigDict(extra="forbid")

    number: int = 0
    id: str = ""
    title: str
    epic_id: str | None = None
    description: str = ""
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.OPEN
    url: str = ""


class StorySummary(BaseModel):
    """Lightweight story info returned by manifest-based listing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    epic_id: str = ""
    status: str = "open"


class EpicCreate(BaseModel):
    """Payload for creating an epic issue."""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    release: str = ""
    spec_refs: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    milestone: str | None = None


class EpicDetail(BaseModel):
    """Full epic read back from the remote."""

    model_config = ConfigDict(extra="forbid")

    number: int = 0
    id: str = ""
    title: str
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.OPEN
    url: str = ""


class EpicSummary(BaseModel):
    """Lightweight epic info for listing and hierarchy checks."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: str = "open"
