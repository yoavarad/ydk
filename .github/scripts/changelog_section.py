"""CI helper for release.yml.

Usage:
    changelog_section.py version [PYPROJECT]          print [project].version
    changelog_section.py section VERSION [CHANGELOG]  print that version's changelog body
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def project_version(text: str) -> str:
    """Return `version` from the [project] table of pyproject.toml text."""
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project:
            m = re.match(r'version\s*=\s*"([^"]+)"', stripped)
            if m:
                return m.group(1)
    raise LookupError("no [project].version found")


def extract_section(changelog: str, version: str) -> str:
    """Return the body of the `## vX.Y.Z` section, without its heading."""
    version = version.removeprefix("v")
    lines = changelog.splitlines()
    heading = re.compile(rf"^##\s+v?{re.escape(version)}(\s|$)")
    start = next((i for i, ln in enumerate(lines) if heading.match(ln)), None)
    if start is None:
        raise LookupError(f"version {version} not found in changelog")
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^##\s", lines[i])), len(lines))
    body = "\n".join(lines[start + 1 : end]).strip()
    if not body:
        raise LookupError(f"changelog section for {version} is empty")
    return body + "\n"


def main(argv: list[str]) -> int:
    try:
        if argv and argv[0] == "version":
            print(project_version(Path(argv[1] if len(argv) > 1 else "pyproject.toml").read_text(encoding="utf-8")))
            return 0
        if len(argv) >= 2 and argv[0] == "section":
            path = Path(argv[2] if len(argv) > 2 else "CHANGELOG.md")
            sys.stdout.write(extract_section(path.read_text(encoding="utf-8"), argv[1]))
            return 0
    except (LookupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
