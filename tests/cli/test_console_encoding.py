"""CLI must survive a cp1252 console and UTF-8 mode when printing non-cp1252 text."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = str(Path(__file__).resolve().parents[2] / "src")

_SNIPPET = "\n".join(
    [
        "import sys",
        "import ydk.cli",
        "from rich.console import Console",
        "Console().print('em\\u2014dash \\u2713 check')",
        "print('plain \\u2014 \\u2713')",
        "sys.stderr.write('err \\u2014 \\u2713')",
    ]
)


@pytest.mark.parametrize("env_extra", [{"PYTHONIOENCODING": "cp1252"}, {"PYTHONUTF8": "1"}])
def test_non_cp1252_output_does_not_crash(env_extra: dict[str, str]) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env.update(env_extra)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, "-c", _SNIPPET],
        capture_output=True,
        env=env,
        check=False,
    )
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert "UnicodeEncodeError" not in stderr
    assert "✓".encode() in result.stdout


def test_child_non_ascii_bytes_decode_with_replace() -> None:
    code = "import sys; sys.stdout.buffer.write(bytes([111, 107, 32, 255, 254, 32, 226, 128, 148]))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("ok ")
