"""Tests for service protocol definitions."""

from __future__ import annotations

import ydk.services
from ydk.services import protocols


def test_service_protocols_exported() -> None:
    assert {"GitService", "RemoteService"} <= set(ydk.services.__all__)


def test_stale_llm_provider_protocol_removed() -> None:
    # The canonical LLM protocol lives in ydk.core.llm_provider; the unused async
    # duplicate that used to live here must not come back.
    assert not hasattr(protocols, "LLMProvider")
    assert "LLMProvider" not in ydk.services.__all__
