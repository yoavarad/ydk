#!/usr/bin/env python3
"""
Generator: agent-skills
Vendors the csharp-development-best-practices agent skill into the target repo:
  - .claude/skills/csharp-development-best-practices/SKILL.md
  - .claude/skills/csharp-development-best-practices/references/csharp-development-best-practices.md

Files are copied verbatim from templates/skills/ (no Jinja rendering -- the
Markdown contains C# braces that must not be interpreted as template syntax).

Input: none (inputs: [] in manifest.yaml) -- always emits the same files.
"""

from __future__ import annotations

import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "templates" / "skills"
OUTPUT_ROOT = ".claude/skills"


def main() -> None:
    output = [
        {
            "path": f"{OUTPUT_ROOT}/{path.relative_to(SKILLS_DIR).as_posix()}",
            "content": path.read_text(encoding="utf-8"),
        }
        for path in sorted(SKILLS_DIR.rglob("*.md"))
    ]
    print(json.dumps(output))


if __name__ == "__main__":
    main()
