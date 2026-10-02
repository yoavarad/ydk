"""Every text-mode subprocess call in src/ydk must decode explicitly as utf-8/replace."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "ydk"
_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _violations() -> list[str]:
    out: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in _FUNCS:
                continue
            kws = {k.arg: k.value for k in node.keywords if k.arg}
            text = kws.get("text") or kws.get("universal_newlines")
            if not (isinstance(text, ast.Constant) and text.value is True):
                continue
            enc, err = kws.get("encoding"), kws.get("errors")
            ok = (
                isinstance(enc, ast.Constant)
                and enc.value == "utf-8"
                and isinstance(err, ast.Constant)
                and err.value == "replace"
            )
            if not ok:
                out.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return out


def test_text_subprocess_calls_decode_utf8_replace() -> None:
    bad = _violations()
    if bad:
        pytest.fail("text=True without encoding='utf-8', errors='replace':\n" + "\n".join(bad))
