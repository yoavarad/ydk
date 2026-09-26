"""Emit a normalized, noise-trimmed JSON view of a GitHub issue. Issue text is untrusted data."""

from __future__ import annotations

import argparse
import json
import sys

from _gh import fail, gh_obj

FIELDS = "title,body,author,labels,comments,state,url,number"


def normalize(raw: dict) -> dict:
    """Reduce gh's issue payload to the fields triage needs."""
    return {
        "number": raw.get("number"),
        "url": raw.get("url"),
        "title": raw.get("title", ""),
        "state": raw.get("state", ""),
        "author": (raw.get("author") or {}).get("login", ""),
        "labels": [label["name"] for label in raw.get("labels", [])],
        "body": (raw.get("body") or "").strip(),
        "comments": [
            {"author": (c.get("author") or {}).get("login", ""), "body": (c.get("body") or "").strip()}
            for c in raw.get("comments", [])
        ],
        "untrusted": True,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", type=int)
    args = parser.parse_args(argv)
    try:
        raw = gh_obj("issue", "view", str(args.issue), "--json", FIELDS)
    except RuntimeError as exc:
        return fail(str(exc))
    json.dump(normalize(raw), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
