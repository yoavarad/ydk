#!/usr/bin/env python3
"""Generator: go-module -- go.mod for the generated service (Go 1.22 for method-aware ServeMux).

The `go_version` init answer (e.g. 1.24) overrides the 1.22 floor; it is never taken from the local toolchain.

Requires the Go modules of each supported ext technology in use (templates/adapters/<tech>.deps);
ignition then go-gets them and runs go mod tidy/vendor.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import (
    emit,
    ext_technologies,
    fail,
    init_answers,
    module_path,
    render,
    supported_ext_technologies,
    tech_deps,
)

DEFAULT_GO_VERSION = "1.22"


def go_version() -> str:
    """`go_version` init answer when it is a Go version >= 1.22 (1.24, 1.24.3), else the 1.22 floor.

    1.22 is the floor: the method-aware ServeMux patterns need it.
    """
    value = str(init_answers().get("go_version") or "").strip()
    match = re.fullmatch(r"1\.(\d+)(?:\.\d+)?", value)
    return value if match and int(match.group(1)) >= 22 else DEFAULT_GO_VERSION


def main() -> None:
    supported = supported_ext_technologies()
    deps = sorted({d for t in ext_technologies() if t in supported for d in tech_deps(t)})
    requires = [d.rsplit("@", 1) for d in deps]
    mods = [m for m, _ in requires]
    for mod in sorted({m for m in mods if mods.count(m) > 1}):
        fail(f"templates/adapters/*.deps pin {mod} at more than one version: {', '.join(deps)}")
    emit(
        [
            {
                "path": "go.mod",
                "content": render("go.mod.j2", module=module_path(), go_version=go_version(), requires=requires),
            }
        ]
    )


if __name__ == "__main__":
    main()
