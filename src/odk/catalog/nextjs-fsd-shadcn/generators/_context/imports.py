"""TypeScript import statement builder with deduplication."""

from __future__ import annotations

from collections import defaultdict


class ImportSet:
    """
    Accumulates TypeScript import statements and renders them deduplicated and sorted.

    Usage:
        imp = ImportSet()
        imp.add_named("@tanstack/react-query", ["useQuery", "useMutation"])
        imp.add_type("@/shared/api/generated/types", "Strategy")
        imp.add_side_effect("./polyfills")
        for line in imp.render():
            print(line)
    """

    def __init__(self) -> None:
        # module → set of named imports
        self._named: dict[str, set[str]] = defaultdict(set)
        # module → set of type-only named imports
        self._type_named: dict[str, set[str]] = defaultdict(set)
        # side-effect imports (no bindings)
        self._side_effects: set[str] = set()

    def add_named(self, module: str, names: list[str]) -> None:
        """Add `import { name1, name2 } from 'module'`."""
        self._named[module].update(names)

    def add_type(self, module: str, *names: str) -> None:
        """Add `import type { Name } from 'module'`."""
        self._type_named[module].update(names)

    def add_side_effect(self, module: str) -> None:
        """Add `import 'module'`."""
        self._side_effects.add(module)

    # Convenience alias used by existing generator code
    def add(self, module: str) -> None:
        """Add a side-effect import."""
        self.add_side_effect(module)

    def render(self) -> list[str]:
        """
        Return sorted import lines.  Order:
          1. `import type { ... }` lines (alphabetical by module)
          2. `import { ... }` lines (alphabetical by module)
          3. `import 'module'` side-effect lines (alphabetical)
        """
        lines: list[str] = []

        for module in sorted(self._type_named):
            names = sorted(self._type_named[module])
            lines.append(f"import type {{ {', '.join(names)} }} from '{module}'")

        for module in sorted(self._named):
            names = sorted(self._named[module])
            lines.append(f"import {{ {', '.join(names)} }} from '{module}'")

        for module in sorted(self._side_effects):
            lines.append(f"import '{module}'")

        return lines
