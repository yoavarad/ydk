"""Small Go-source helpers for the ``task done`` skip check.

``blank_comments_and_strings`` replaces comment text and string/rune contents
with spaces (keeping quotes and line numbering) so skip patterns only match
real code. ``added_lines`` maps each file in a ``git diff -U0`` to the
new-side line numbers it adds.
"""

from __future__ import annotations

import re

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def blank_comments_and_strings(text: str) -> list[str]:
    """Return *text*'s lines with comments removed and string/rune contents blanked."""
    out: list[str] = []
    state = "code"  # code | line | block | str | raw | rune
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == "\n":
            if state in ("line", "str", "rune"):  # str/rune can't span lines; don't let a stray quote leak
                state = "code"
            out.append(ch)
        elif state == "code":
            if ch == "/" and nxt == "/":
                state = "line"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block"
                i += 1
            else:
                state = {'"': "str", "`": "raw", "'": "rune"}.get(ch, "code")
                out.append(ch)
        elif state == "block":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 1
        elif state == "line":
            pass
        elif ch == "\\" and state in ("str", "rune"):
            out.append("  " if nxt and nxt != "\n" else " ")
            i += 1 if nxt and nxt != "\n" else 0
        elif (state, ch) in (("str", '"'), ("raw", "`"), ("rune", "'")):
            state = "code"
            out.append(ch)
        else:
            out.append(" ")
        i += 1
    return [line.rstrip() for line in "".join(out).split("\n")]


def added_lines(diff: str) -> dict[str, set[int]]:
    """Map new-side path -> added line numbers from a zero-context unified diff."""
    result: dict[str, set[int]] = {}
    path: str | None = None
    lineno = 0
    remaining = 0  # new-side lines left in the current hunk; header lines only count outside hunks
    for line in diff.split("\n"):
        if remaining > 0:
            if line.startswith("+"):
                if path:
                    result.setdefault(path, set()).add(lineno)
                lineno += 1
                remaining -= 1
            elif line.startswith(" "):
                lineno += 1
                remaining -= 1
            continue
        if line.startswith("+++ "):
            target = _unquote(line[4:].rstrip("\t\r"))
            path = target[2:] if target.startswith("b/") else None
            continue
        hunk = _HUNK_RE.match(line)
        if hunk:
            lineno = int(hunk.group(1))
            remaining = int(hunk.group(2)) if hunk.group(2) is not None else 1
    return result


def _unquote(path: str) -> str:
    """Undo git's C-style path quoting (``"b/p\\303\\251.go"`` -> ``b/pé.go``)."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    raw = path[1:-1].encode("latin-1", errors="backslashreplace").decode("unicode_escape")
    return raw.encode("latin-1", errors="replace").decode("utf-8", errors="replace")
