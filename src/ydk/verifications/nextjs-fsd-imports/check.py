#!/usr/bin/env python3
"""Verification plugin: FSD layer isolation -- Next.js App Router variant.

Layer order (high to low): app > _pages > widgets > features > entities > shared
"""

import json
import sys
import time
from pathlib import Path

LAYER_ORDER = ["app", "_pages", "widgets", "features", "entities", "shared"]


def get_layer(filepath: str) -> str | None:
    """Determine FSD layer from file path."""
    for prefix, layer in [
        ("src/app/", "app"),
        ("src/_pages/", "_pages"),
        ("src/widgets/", "widgets"),
        ("src/features/", "features"),
        ("src/entities/", "entities"),
        ("src/shared/", "shared"),
    ]:
        if filepath.startswith(prefix):
            return layer
    return None


def layer_index(layer: str) -> int:
    """Run the nextjs-fsd-imports verification check."""
    try:
        return LAYER_ORDER.index(layer)
    except ValueError:
        return 99


def main() -> None:
    """Run the nextjs-fsd-imports verification check."""
    context = json.loads(sys.stdin.read())
    project_root = context["project_root"]
    start = time.time()

    root = Path(project_root)
    src_dir = root / "src"

    if not src_dir.is_dir():
        result = {
            "name": "nextjs-fsd-imports",
            "passed": True,
            "output": "PASS: no src/ directory found",
            "duration_seconds": round(time.time() - start, 1),
            "detail": None,
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

    failures = 0
    messages: list[str] = []

    for ext in ("*.ts", "*.tsx"):
        for f in src_dir.rglob(ext):
            if "node_modules" in str(f) or "__pycache__" in str(f):
                continue

            rel = str(f.relative_to(root))
            file_layer = get_layer(rel)
            if not file_layer:
                continue

            file_idx = layer_index(file_layer)

            try:
                for _i, line in enumerate(f.read_text().splitlines(), 1):
                    if "//" in line:
                        continue
                    if not (line.startswith("import") or "from " in line):
                        continue

                    for layer in LAYER_ORDER:
                        if f"@/{layer}/" in line:
                            imported_idx = layer_index(layer)
                            if imported_idx <= file_idx:
                                messages.append(
                                    f"FAIL: {rel} ({file_layer}) imports from {layer} "
                                    f"(same/higher layer)\n  {line.strip()}"
                                )
                                failures += 1
            except OSError:
                pass

    passed = failures == 0
    output = "PASS: FSD imports valid" if passed else "\n".join(messages)

    result = {
        "name": "nextjs-fsd-imports",
        "passed": passed,
        "output": output,
        "duration_seconds": round(time.time() - start, 1),
        "detail": {"failures": failures},
    }
    json.dump(result, sys.stdout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
