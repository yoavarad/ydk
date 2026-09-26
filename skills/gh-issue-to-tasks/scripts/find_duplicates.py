"""Find likely duplicates of an issue among open GitHub issues and local .ydk/tasks files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _gh import fail, gh_json, gh_obj

STOPWORDS = frozenset({"the", "and", "for", "with", "when", "not"})
MIN_OVERLAP = 0.5


def keywords(text: str) -> set[str]:
    """Lowercased alphanumeric tokens of length >= 3 minus stopwords."""
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in STOPWORDS}


def overlap(a: set[str], b: set[str]) -> float:
    """Share of the smaller keyword set present in the other."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def local_task_titles(tasks_dir: Path) -> list[tuple[str, str]]:
    """Return (id, title) pairs from task markdown front matter."""
    found: list[tuple[str, str]] = []
    if not tasks_dir.is_dir():
        return found
    for path in sorted(tasks_dir.glob("*.md")):
        title = ""
        for line in path.read_text(encoding="utf-8").splitlines()[:10]:
            if line.startswith("title:"):
                title = line.removeprefix("title:").strip()
        if title:
            found.append((path.stem, title))
    return found


def find_duplicates(number: int, title: str, tasks_dir: Path) -> list[dict]:
    """Rank open issues and local tasks whose title overlaps the given title."""
    target = keywords(title)
    hits: list[dict] = []
    issues = gh_json("issue", "list", "--state", "open", "--limit", "200", "--json", "number,title,url")
    for issue in issues:
        if issue["number"] == number:
            continue
        score = overlap(target, keywords(issue["title"]))
        if score >= MIN_OVERLAP:
            hits.append(
                {"kind": "issue", "id": issue["number"], "title": issue["title"], "url": issue["url"], "score": score}
            )
    for task_id, task_title in local_task_titles(tasks_dir):
        score = overlap(target, keywords(task_title))
        if score >= MIN_OVERLAP:
            hits.append({"kind": "task", "id": task_id, "title": task_title, "score": score})
    return sorted(hits, key=lambda h: -h["score"])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", type=int)
    parser.add_argument("--tasks-dir", type=Path, default=Path(".ydk/tasks"))
    args = parser.parse_args(argv)
    try:
        raw = gh_obj("issue", "view", str(args.issue), "--json", "title")
        hits = find_duplicates(args.issue, raw["title"], args.tasks_dir)
    except RuntimeError as exc:
        return fail(str(exc))
    json.dump(hits, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
