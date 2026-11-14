"""Lint-style test: text-mode file I/O in src/ydk must pass an explicit encoding."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "ydk"
EXCLUDED = ("verifications",)


def is_bare_text_io(node: ast.Call) -> bool:
    """Return True for a text-mode read_text/write_text/open call lacking encoding."""
    if any(kw.arg == "encoding" or kw.arg is None for kw in node.keywords):
        return False
    func = node.func
    n = len(node.args)
    if isinstance(func, ast.Name):
        return func.id == "open" and _is_text_open(node, mode_index=1)
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "read_text":
        return n == 0
    if func.attr == "write_text":
        return n == 1
    is_os = isinstance(func.value, ast.Name) and func.value.id == "os"
    return func.attr == "open" and not is_os and _is_text_open(node, mode_index=0)


def find_bare_text_io(tree: ast.AST) -> list[int]:
    """Return line numbers of bare text-mode I/O calls in a parsed module."""
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and is_bare_text_io(n)]


def _is_text_open(node: ast.Call, mode_index: int) -> bool:
    mode: ast.expr | None = node.args[mode_index] if len(node.args) > mode_index else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode = kw.value
    if mode is None:
        return True
    if isinstance(mode, ast.IfExp):
        return any(_mode_is_text(m) for m in (mode.body, mode.orelse))
    return _mode_is_text(mode)


def _mode_is_text(mode: ast.expr) -> bool:
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" not in mode.value


def test_no_bare_text_io_in_src() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        if rel.parts[0] in EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(f"{rel.as_posix()}:{ln}" for ln in find_bare_text_io(tree))
    assert not offenders, "text-mode I/O without encoding='utf-8':\n" + "\n".join(offenders)


def test_detector_flags_and_accepts() -> None:
    bad = ast.parse("p.read_text()\np.write_text(x)\nopen(f)\np.open()\nopen(f, 'r' if a else 'w')\n")
    good = ast.parse(
        "p.read_text(encoding='utf-8')\np.write_text(x, encoding='utf-8')\nopen(f, 'rb')\n"
        "p.open('wb')\nos.open(p, 1)\nopen(f, encoding='utf-8')\n"
    )
    assert find_bare_text_io(bad) == [1, 2, 3, 4, 5]
    assert find_bare_text_io(good) == []
