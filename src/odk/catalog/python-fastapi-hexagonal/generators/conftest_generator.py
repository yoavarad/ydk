#!/usr/bin/env python3
"""
Generator: conftest
Generate tests/conftest.py with all fake repository fixtures pre-wired.
Input: ODK entity components
Output: tests/conftest.py (single file)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add generators dir to path for _context imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from _context.naming import derive_name, to_snake
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def main() -> None:
    artifact_path = os.environ.get("ODK_COMPONENTS_ENTITY", "")
    if not artifact_path or not Path(artifact_path).exists():
        print("Error: ODK_COMPONENTS_ENTITY not set or file not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    entities_raw = data if isinstance(data, list) else []

    # Build entity context list — sorted by snake module name for ruff I001
    entities = []
    fake_imports = []
    for entity in sorted(entities_raw, key=lambda e: to_snake(derive_name(e)) + "_repository"):
        name = derive_name(entity)
        snake = to_snake(name)
        entities.append({"name": name, "snake_name": snake})
        fake_imports.append(f"from tests.fakes.fake_{snake}_repository import Fake{name}Repository")

    # Set up Jinja2
    templates_dir = Path(__file__).parent.parent / "templates" / "tests"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("conftest.py.j2")

    context = {
        "entities": entities,
        "fake_imports": fake_imports,
    }
    content = template.render(**context).rstrip() + "\n"

    output = [{"path": "tests/conftest.py", "content": content}]

    # Generate __init__.py for all test subdirectories
    init_paths = [
        "tests/__init__.py",
        "tests/fakes/__init__.py",
        "tests/unit/__init__.py",
        "tests/unit/core/__init__.py",
        "tests/unit/core/services/__init__.py",
        "tests/contracts/__init__.py",
        "tests/integration/__init__.py",
        "tests/integration/api/__init__.py",
    ]
    for p in init_paths:
        output.append({"path": p, "content": ""})

    print(json.dumps(output))


if __name__ == "__main__":
    main()
