"""Render a verbose YDK task description from a JSON spec plus the source issue URL (no LLM tokens)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED = ("context", "design", "files", "acceptance", "test_strategy")
SECTIONS = (
    ("Context", "context"),
    ("Root cause / design", "design"),
    ("Files to touch", "files"),
    ("Acceptance criteria", "acceptance"),
    ("Test strategy", "test_strategy"),
)


def _fmt(value: str | list[str], bullet: str) -> str:
    if isinstance(value, list):
        return "\n".join(f"{bullet}{item}" for item in value)
    return value


def render(spec: dict, issue_url: str) -> str:
    """Build the markdown body; raise ValueError when a required section is missing or empty."""
    missing = [key for key in REQUIRED if not spec.get(key)]
    if missing:
        raise ValueError(f"spec missing required keys: {', '.join(missing)}")
    if not issue_url:
        raise ValueError("issue_url is required")
    parts = [f"Source issue: {issue_url}"]
    for heading, key in SECTIONS:
        bullet = "- [ ] " if key == "acceptance" else "- "
        parts.append(f"## {heading}\n{_fmt(spec[key], bullet)}")
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: write to --out or stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="JSON spec file")
    parser.add_argument("--issue-url", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        body = render(json.loads(args.spec.read_text(encoding="utf-8")), args.issue_url)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
