"""Claude Code PreToolUse hook: run local CI mirror checks before `gh pr create`.

Exit 2 (block, stderr fed back to Claude) when pre-push checks or the PR body check fail.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def flag_value(args: list[str], *names: str) -> str | None:
    """Return the value of the first matching flag (`-f v`, `--flag v`, `--flag=v`)."""
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            return unquote(args[i + 1])
        for name in names:
            if name.startswith("--") and arg.startswith(name + "="):
                return unquote(arg.split("=", 1)[1])
    return None


def unquote(value: str) -> str:
    """Strip one pair of matching surrounding quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def main() -> int:
    """Run checks for `gh pr create` commands; return 2 to block on failure."""
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    try:
        args = shlex.split(command, posix=False)
    except ValueError:
        return 0
    if not any(args[i : i + 3] == ["gh", "pr", "create"] for i in range(len(args))):
        return 0

    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    outputs: list[str] = []
    failed = False

    def check(cmd: list[str]) -> None:
        nonlocal failed
        env = {**os.environ, "PYTHONUTF8": "1"}
        try:
            result = subprocess.run(cmd, cwd=root, env=env, capture_output=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            outputs.append(f"{cmd[0]}: {exc}")
            failed = True
            return
        outputs.append(result.stdout + result.stderr)
        failed = failed or result.returncode != 0

    check([sys.executable, str(Path(root) / ".githooks" / "pre-push")])

    body_file = flag_value(args, "--body-file", "-F")
    body = flag_value(args, "--body", "-b")
    if body_file is not None and not Path(body_file).is_file():
        body_file = None
    elif body_file is None and body is not None and not body.startswith("$("):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp.write(body)
        body_file = tmp.name
    if body_file is not None:
        base = flag_value(args, "--base", "-B") or "main"
        has_base = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"origin/{base}"], cwd=root, capture_output=True
        )
        try:
            if has_base.returncode == 0:
                check(
                    [
                        *["uv", "run", "ydk", "verify", "pr-body"],
                        *["--body-file", str(Path(body_file).resolve()), "--base-ref", f"origin/{base}"],
                    ]
                )
        finally:
            if body is not None and flag_value(args, "--body-file", "-F") is None:
                Path(body_file).unlink(missing_ok=True)

    if failed:
        sys.stderr.reconfigure(encoding="utf-8")
        text = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(outputs))
        print("Pre-PR CI checks failed — fix before opening PR:", file=sys.stderr)
        print(text, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
