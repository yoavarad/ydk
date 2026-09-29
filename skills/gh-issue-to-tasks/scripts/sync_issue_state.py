"""Retire every linked issue whose YDK tasks (GitHub issues) are all closed. Wraps `ydk task sync-issues`."""

from __future__ import annotations

import argparse

from _gh import fail

from ydk.core.linked_issues import sync


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        retired = sync(args.dry_run)
    except RuntimeError as exc:
        return fail(str(exc))
    print("retired: " + (", ".join(f"#{n}" for n in retired) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
