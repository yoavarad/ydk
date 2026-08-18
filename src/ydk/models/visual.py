"""Visual companion models for browser-based design annotation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SessionStatus(StrEnum):
    """Lifecycle state of a visual session."""

    starting = "starting"
    running = "running"
    stopped = "stopped"
    error = "error"


class VisualSession(BaseModel):
    """State of a running visual companion session."""

    model_config = ConfigDict(extra="forbid")
    id: str
    port: int
    url: str
    content_dir: str
    state_dir: str
    pid: int | None = None
    status: SessionStatus = SessionStatus.starting


class BoundingRect(BaseModel):
    """Absolute pixel bounding box relative to viewport."""

    model_config = ConfigDict(extra="forbid")
    x: float
    y: float
    width: float
    height: float


class ViewportInfo(BaseModel):
    """Viewport and scroll state at annotation time."""

    model_config = ConfigDict(extra="forbid")
    scrollX: float
    scrollY: float
    width: float
    height: float
    devicePixelRatio: float


class RectPct(BaseModel):
    """Percentage-based rectangle relative to an anchor element."""

    model_config = ConfigDict(extra="forbid")
    xPct: float
    yPct: float
    wPct: float
    hPct: float


class AnchorInfo(BaseModel):
    """Multi-anchor element identification for resilient re-resolution."""

    model_config = ConfigDict(extra="forbid")
    cssSelector: str | None = None
    xpath: str | None = None
    textSnippet: str | None = None
    elementTag: str | None = None
    elementId: str | None = None
    dataTestId: str | None = None
    ariaLabel: str | None = None
    fingerprint: str | None = None


class ComponentInfo(BaseModel):
    """Optional React/Vue component metadata from fiber walking."""

    model_config = ConfigDict(extra="forbid")
    name: str
    path: list[str]
    library: str | None = None


class SelectionEvent(BaseModel):
    """User chose a design option."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["selection"]
    choice: str
    choiceText: str | None = None
    timestamp: int
    contentFile: str | None = None


class ElementAnnotationEvent(BaseModel):
    """User annotated a specific DOM element."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["element_annotation"]
    id: str
    comment: str
    anchor: AnchorInfo
    component: ComponentInfo | None = None
    boundingRect: BoundingRect | None = None
    viewport: ViewportInfo | None = None
    screenshotPath: str | None = None
    timestamp: int
    contentFile: str | None = None


class RectangleAnnotationEvent(BaseModel):
    """User drew a rectangle annotation on a region."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["rectangle_annotation"]
    id: str
    comment: str
    anchor: AnchorInfo | None = None
    rect: RectPct
    absoluteRect: BoundingRect | None = None
    component: ComponentInfo | None = None
    viewport: ViewportInfo | None = None
    screenshotPath: str | None = None
    timestamp: int
    contentFile: str | None = None


FeedbackEvent = SelectionEvent | ElementAnnotationEvent | RectangleAnnotationEvent
