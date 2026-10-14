#!/usr/bin/env python3
"""Generator: web-pages -- web/<name>.html per ydk:page plus web/web.go embedding them (go:embed)."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import app_name, comment, emit, load, render, split_id


def _safe(text: object) -> str:
    """Escaped, single-line, ASCII text that cannot close an HTML comment."""
    return html.escape(comment(text)).replace("--", "- -")


def main() -> None:
    pages = load("page")
    if not pages:
        emit([])
        return
    files = [{"path": "web/web.go", "content": render("web/web.go.j2")}]
    title = app_name()
    for page in pages:
        _, name = split_id(str(page.get("id", "")))
        sections = []
        for section in page.get("sections") or []:
            if not isinstance(section, dict):
                continue
            sections.append(
                {
                    "name": re.sub(r"[^A-Za-z0-9_-]", "-", str(section.get("name", "section"))),
                    "description": _safe(section.get("description")),
                    "data_sources": _safe(", ".join(str(d) for d in section.get("data_sources") or [])),
                }
            )
        content = render(
            "web/page.html.j2",
            title=html.escape(title),
            id=_safe(page.get("id")),
            description=_safe(page.get("description")),
            layout=_safe(page.get("layout")),
            sections=sections,
        )
        files.append({"path": f"web/{name}.html", "content": content})
    emit(files)


if __name__ == "__main__":
    main()
