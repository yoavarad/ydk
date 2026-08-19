"""Tests for checkpoint review guide generation."""

from __future__ import annotations

import json

from ydk.core.checkpoint import CheckpointGenerator
from ydk.core.llm_provider import LLMProvider
from ydk.models.checkpoint import CheckpointPreview
from ydk.models.pm import TaskDetail


class MockLLMProvider:
    """Mock LLM provider that returns a canned response."""

    def __init__(self, response: str) -> None:
        self._response = response

    def invoke(self, prompt: str) -> str:
        return self._response


class FailingLLMProvider:
    """LLM provider that returns invalid JSON."""

    def invoke(self, prompt: str) -> str:
        return "not valid json"


SAMPLE_DIFF = """\
diff --git a/src/app/models.py b/src/app/models.py
--- a/src/app/models.py
+++ b/src/app/models.py
@@ -1,3 +1,5 @@
+class Order:
+    pass
 class User:
     pass
diff --git a/tests/test_models.py b/tests/test_models.py
--- a/tests/test_models.py
+++ b/tests/test_models.py
@@ -1,3 +1,6 @@
+def test_order():
+    assert True
+
 def test_user():
     assert True
"""


class TestCheckpointGenerator:
    def test_empty_diff_returns_empty_preview(self) -> None:
        gen = CheckpointGenerator()
        result = gen.generate("")
        assert result.intent == "Empty diff — no changes detected."
        assert result.files_changed == 0

    def test_fallback_groups_by_directory(self) -> None:
        gen = CheckpointGenerator()
        result = gen.generate(SAMPLE_DIFF)
        assert isinstance(result, CheckpointPreview)
        assert result.files_changed == 2
        assert result.insertions == 5
        assert result.deletions == 0
        # Fallback groups by directory
        concern_names = [c.concern for c in result.concerns]
        assert "src" in concern_names
        assert "tests" in concern_names

    def test_fallback_with_task_context(self) -> None:
        gen = CheckpointGenerator()
        task = TaskDetail(title="Add Order model", id="T-001")
        result = gen.generate(SAMPLE_DIFF, task=task)
        assert result.intent == "Add Order model"

    def test_llm_provider_used_when_available(self) -> None:
        response = json.dumps(
            {
                "intent": "Add order processing",
                "concerns": [
                    {
                        "concern": "domain model",
                        "files": ["src/app/models.py"],
                        "summary": "New Order class added",
                    }
                ],
                "blast_radius": [
                    {
                        "location": "src/app/models.py:1",
                        "risk": "New model may need migrations",
                        "suggestion": "Check ORM migrations",
                    }
                ],
                "testing_suggestions": ["Add unit tests for Order"],
            }
        )
        provider = MockLLMProvider(response)
        gen = CheckpointGenerator()
        result = gen.generate(SAMPLE_DIFF, llm_provider=provider)

        assert result.intent == "Add order processing"
        assert len(result.concerns) == 1
        assert result.concerns[0].concern == "domain model"
        assert len(result.blast_radius) == 1
        assert result.testing_suggestions == ["Add unit tests for Order"]

    def test_fallback_when_llm_returns_bad_json(self) -> None:
        provider = FailingLLMProvider()
        gen = CheckpointGenerator()
        result = gen.generate(SAMPLE_DIFF, llm_provider=provider)
        # Should fall back to directory grouping
        assert result.files_changed == 2
        assert len(result.concerns) > 0

    def test_blast_radius_detects_init_files(self) -> None:
        diff = """\
diff --git a/src/__init__.py b/src/__init__.py
--- a/src/__init__.py
+++ b/src/__init__.py
@@ -1 +1,2 @@
+import new_module
 import old_module
"""
        gen = CheckpointGenerator()
        result = gen.generate(diff)
        assert any("__init__" in b.location for b in result.blast_radius)

    def test_llm_provider_protocol(self) -> None:
        provider = MockLLMProvider("test")
        assert isinstance(provider, LLMProvider)

    def test_code_fenced_llm_response(self) -> None:
        inner = json.dumps(
            {
                "intent": "Refactor auth",
                "concerns": [],
                "blast_radius": [],
                "testing_suggestions": [],
            }
        )
        response = f"```json\n{inner}\n```"
        provider = MockLLMProvider(response)
        gen = CheckpointGenerator()
        result = gen.generate(SAMPLE_DIFF, llm_provider=provider)
        assert result.intent == "Refactor auth"
