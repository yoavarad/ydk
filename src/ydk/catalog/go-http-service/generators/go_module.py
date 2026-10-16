#!/usr/bin/env python3
"""Generator: go-module -- go.mod for the generated service (Go 1.22 for method-aware ServeMux).

Requires the Go modules of each supported ext technology in use (templates/adapters/<tech>.deps);
ignition then go-gets them and runs go mod tidy/vendor.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import emit, ext_technologies, fail, module_path, render, supported_ext_technologies, tech_deps


def main() -> None:
    supported = supported_ext_technologies()
    deps = sorted({d for t in ext_technologies() if t in supported for d in tech_deps(t)})
    requires = [d.rsplit("@", 1) for d in deps]
    mods = [m for m, _ in requires]
    for mod in sorted({m for m in mods if mods.count(m) > 1}):
        fail(f"templates/adapters/*.deps pin {mod} at more than one version: {', '.join(deps)}")
    emit([{"path": "go.mod", "content": render("go.mod.j2", module=module_path(), requires=requires)}])


if __name__ == "__main__":
    main()
