#!/usr/bin/env python3
"""Generator: go-module -- go.mod for the generated service (Go 1.22 for method-aware ServeMux)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import emit, module_path, render


def main() -> None:
    emit([{"path": "go.mod", "content": render("go.mod.j2", module=module_path())}])


if __name__ == "__main__":
    main()
