#!/usr/bin/env python3
"""
Generator: e2e-test-bodies
Generate end-to-end test bodies from test-plan.yaml e2e_tests.
Falls back to stubs derived from user-stories.yaml when test-plan.yaml is absent.

Input: test-plan.yaml (YDK_COMPONENTS_TEST_PLAN), user-stories.yaml (YDK_COMPONENTS_USER_STORY)
Output: tests/e2e/test_{story_id_snake}.py per e2e story
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict:
    if path and Path(path).exists():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {}


def _story_id_to_snake(story_id: str) -> str:
    """'US-001' → 'us_001', 'US-001-error' → 'us_001_error'"""
    return re.sub(r"[^a-z0-9]+", "_", story_id.lower()).strip("_")


def _title_to_snake(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _title_to_class(title: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split()
    return "".join(w.capitalize() for w in words)


def _story_id_to_class(story_id: str) -> str:
    """'US-001' → 'US001', 'US-001-error' → 'US001Error'"""
    parts = re.split(r"[-_]", story_id)
    return "".join(p.capitalize() for p in parts)


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------

FILE_HEADER_TMPL = """\
\"\"\"End-to-end test: {title}\"\"\"
from __future__ import annotations

import pytest
import pytest_asyncio  # noqa: F401
from httpx import ASGITransport, AsyncClient  # noqa: F401

from app.main import app  # noqa: F401


@pytest.mark.asyncio
class Test{class_name}:
"""


def _render_e2e_test(story: dict) -> str:
    story_id = story.get("story", "unknown")
    title = story.get("title", story_id)
    setup = story.get("setup", "")
    teardown = story.get("teardown", "")
    steps = story.get("steps", [])

    title_snake = _title_to_snake(title)

    lines = [
        f"    async def test_{title_snake}(self, client: AsyncClient) -> None:",
        f"        # Story: {title}",
    ]
    if setup:
        lines.append(f"        # Setup: {setup}")
    lines.append(f"        # TODO[ydk:test:e2e:{story_id}@test-plan.yaml]")
    if steps:
        lines.append("        # Steps:")
        for i, step in enumerate(steps, 1):
            action = step.get("action", "")
            assert_str = step.get("assert", "")
            lines.append(f"        #   {i}. {action} → assert: {assert_str}")
    if teardown:
        lines.append(f"        # Teardown: {teardown}")
    lines.append("        raise NotImplementedError")
    return "\n".join(lines) + "\n"


def _render_e2e_stub_from_story(story: dict) -> str:
    """Fallback when test-plan.yaml has no e2e entry for this user story."""
    story_id = story.get("id", "unknown")
    title = story.get("title", story_id)
    criteria = story.get("acceptance_criteria", [])
    error_flows = story.get("error_flows", [])

    title_snake = _title_to_snake(title)

    lines = [
        f"    async def test_{title_snake}(self, client: AsyncClient) -> None:",
        f"        # Story: {story_id} — {title}",
        f"        # TODO[ydk:test:e2e:{story_id}@user-stories.yaml]",
        "        # IMPLEMENT this e2e flow",
    ]
    if criteria:
        lines.append("        # Acceptance criteria:")
        for c in criteria:
            lines.append(f"        #   - {c}")
    if error_flows:
        lines.append("        # Error flows:")
        for ef in error_flows:
            trigger = ef.get("trigger", "")
            expected = ef.get("expected_behavior", "")
            lines.append(f"        #   - {trigger}: {expected}")
    lines.append("        raise NotImplementedError")
    return "\n".join(lines) + "\n"


def build_e2e_file_from_plan(story: dict) -> tuple[str, str]:
    """Returns (filename, content) for a test-plan e2e story."""
    story_id = story.get("story", "unknown")
    title = story.get("title", story_id)
    class_name = _story_id_to_class(story_id)

    header = FILE_HEADER_TMPL.format(title=title, class_name=class_name)
    body = _render_e2e_test(story)

    filename = f"test_{_story_id_to_snake(story_id)}.py"
    return filename, header + "\n" + body


def build_e2e_file_from_user_story(story: dict) -> tuple[str, str]:
    """Returns (filename, content) for a user-stories.yaml story (fallback)."""
    story_id = story.get("id", "unknown")
    title = story.get("title", story_id)
    class_name = _story_id_to_class(story_id)

    header = FILE_HEADER_TMPL.format(title=title, class_name=class_name)
    body = _render_e2e_stub_from_story(story)

    filename = f"test_{_story_id_to_snake(story_id)}.py"
    return filename, header + "\n" + body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    test_plan_path = os.environ.get("YDK_COMPONENTS_TEST_PLAN", "")
    user_stories_path = os.environ.get("YDK_COMPONENTS_USER_STORY", "")

    plan_data = _load_yaml(test_plan_path)
    stories_data = _load_yaml(user_stories_path)

    e2e_entries = plan_data.get("e2e_tests", [])
    user_stories = stories_data.get("user_stories", [])

    output = []
    seen_files: set[str] = set()

    if e2e_entries:
        # Generate from test-plan e2e_tests
        for story in e2e_entries:
            filename, content = build_e2e_file_from_plan(story)
            if filename not in seen_files:
                seen_files.add(filename)
                output.append({"path": filename, "content": content})
            else:
                # Append to existing content (multiple stories with same id prefix)
                for item in output:
                    if item["path"] == filename:
                        # Add just the test method (skip duplicate header)
                        method_body = _render_e2e_test(story)
                        item["content"] = item["content"].rstrip() + "\n\n" + "    " + method_body.lstrip()
                        break
    elif user_stories:
        # Fallback: generate stubs from user-stories.yaml
        for story in user_stories:
            filename, content = build_e2e_file_from_user_story(story)
            if filename not in seen_files:
                seen_files.add(filename)
                output.append({"path": filename, "content": content})

    print(json.dumps(output))


if __name__ == "__main__":
    main()
