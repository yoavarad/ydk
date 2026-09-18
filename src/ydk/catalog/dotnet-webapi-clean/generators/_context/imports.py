"""C# `using` directive collection/sorting helpers for YDK generators."""

from __future__ import annotations


def sort_usings(usings: set[str] | list[str]) -> list[str]:
    """Dedupe and order namespaces per common C# convention.

    `System` and `System.*` namespaces sort first (alphabetically), followed by
    all other namespaces (alphabetically). Returns bare namespace strings
    (e.g. "System.Collections.Generic"), not full `using X;` statements.
    """
    unique = set(usings)
    system_usings = sorted(u for u in unique if u == "System" or u.startswith("System."))
    other_usings = sorted(u for u in unique if u not in system_usings)
    return system_usings + other_usings


def format_using_block(usings: set[str] | list[str]) -> str:
    """Render namespaces as `using X;` lines ready to prepend to a C# file.

    A blank line separates the `System.*` group from the rest when both are
    present. Returns "" when `usings` is empty.
    """
    ordered = sort_usings(usings)
    if not ordered:
        return ""
    system_usings = [u for u in ordered if u == "System" or u.startswith("System.")]
    other_usings = [u for u in ordered if u not in system_usings]
    lines = [f"using {u};" for u in system_usings]
    if system_usings and other_usings:
        lines.append("")
    lines.extend(f"using {u};" for u in other_usings)
    return "\n".join(lines)
