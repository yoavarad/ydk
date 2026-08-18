"""Naming convention converters for nextjs-fsd-shadcn generators."""

from __future__ import annotations

import re


def derive_name(component: dict) -> str:
    """Derive the component name from its YDK id field.

    Parses "ydk:page:app/dashboard" -> "dashboard"
    Parses "ydk:entity:trading/Strategy" -> "Strategy"
    Parses "ydk:route:strategies/list" -> "list"
    Falls back to component["name"] or component["id"] for legacy data.
    """
    component_id = component.get("id", "")
    if component_id:
        # ydk:type:namespace/Name -> last segment after /
        if "/" in component_id:
            return component_id.rsplit("/", 1)[1]
        # ydk:type:Name -> last segment after :
        parts = component_id.split(":")
        if len(parts) > 1:
            return parts[-1]
    # Legacy fallback
    return component.get("name", component.get("id", "Unknown"))


def to_snake(name: str) -> str:
    """PascalCase or camelCase → snake_case.  StrategyRun → strategy_run"""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def to_pascal(name: str) -> str:
    """snake_case, kebab-case, or camelCase → PascalCase.  strategy-run → StrategyRun"""
    # Split on underscores, hyphens, or camelCase word boundaries
    words = re.split(r"[_\-]", name)
    if len(words) == 1:
        # Might already be PascalCase or camelCase — normalise
        s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        words = s.split("_")
    return "".join(w.capitalize() for w in words if w)


def to_camel(name: str) -> str:
    """snake_case, kebab-case, or PascalCase → camelCase.  StrategyRun → strategyRun"""
    pascal = to_pascal(name)
    if not pascal:
        return pascal
    return pascal[0].lower() + pascal[1:]


def to_kebab(name: str) -> str:
    """PascalCase or camelCase or snake_case → kebab-case.  StrategyRun → strategy-run"""
    snake = to_snake(name)
    return snake.replace("_", "-")


# Alias matching backend convention
snake_to_camel = to_camel


def path_to_component_name(route_path: str) -> str:
    """
    Derive a PascalCase component name from a Next.js route path.
    /strategies/[id]/code  →  StrategiesCodePage
    /  →  HomePage
    """
    if not route_path or route_path == "/":
        return "HomePage"
    # Strip dynamic segments [param] and leading slash
    clean = re.sub(r"\[([^\]]+)\]", "", route_path)
    segments = [s for s in clean.split("/") if s]
    if not segments:
        return "HomePage"
    return "".join(to_pascal(s) for s in segments) + "Page"
