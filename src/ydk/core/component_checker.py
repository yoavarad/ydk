"""Component quality checker — deterministic validation of component manifests."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from ydk.models.evaluation import ComponentFinding

_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# Component types whose names should be kebab-case
_KEBAB_TYPES = {"route", "error", "req"}

# Component types whose names should be PascalCase
_PASCAL_TYPES = {"entity"}


def _load_all_manifests(components_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Load all YAML manifests from the components directory."""
    manifests: list[tuple[Path, dict[str, Any]]] = []
    if not components_dir.is_dir():
        return manifests
    for yaml_file in sorted(components_dir.rglob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        if data and isinstance(data, dict) and "id" in data:
            manifests.append((yaml_file, data))
    return manifests


def _relative_path(file_path: Path, components_dir: Path) -> str:
    """Get a display-friendly relative path for a component file."""
    try:
        return str(file_path.relative_to(components_dir.parent.parent))
    except ValueError:
        return str(file_path)


class ComponentChecker:
    """Deterministic quality checks on component manifests.

    Validates routes, NFRs, entities, naming conventions, and descriptions
    without requiring an LLM.
    """

    def check_all(self, components_dir: Path, schemas_dir: Path) -> list[ComponentFinding]:
        """Run all deterministic checks on every component manifest."""
        manifests = _load_all_manifests(components_dir)
        findings: list[ComponentFinding] = []

        for file_path, data in manifests:
            component_id: str = data.get("id", "")
            rel_path = _relative_path(file_path, components_dir)

            findings.extend(self._check_route(component_id, rel_path, data))
            findings.extend(self._check_nfr(component_id, rel_path, data))
            findings.extend(self._check_entity(component_id, rel_path, data))
            findings.extend(self._check_naming(component_id, rel_path, data))
            findings.extend(self._check_description(component_id, rel_path, data))

        return findings

    def _get_component_type(self, component_id: str) -> str:
        """Extract the type segment from a component ID like ydk:route:..."""
        parts = component_id.split(":", 2)
        return parts[1] if len(parts) >= 2 else ""

    def _get_component_name(self, component_id: str) -> str:
        """Extract the final name segment from a component ID."""
        parts = component_id.split(":", 2)
        if len(parts) < 3:
            return ""
        path_part = parts[2]
        if "/" in path_part:
            return path_part.rsplit("/", 1)[-1]
        return path_part

    # -- Route checks --

    def _check_route(self, component_id: str, file_path: str, data: dict[str, Any]) -> list[ComponentFinding]:
        findings: list[ComponentFinding] = []
        if self._get_component_type(component_id) != "route":
            return findings

        # Check for error responses
        responses = data.get("responses", {})
        if isinstance(responses, dict):
            has_error = any(str(k).startswith(("4", "5")) for k in responses)
            if not has_error:
                findings.append(
                    ComponentFinding(
                        component_id=component_id,
                        file_path=file_path,
                        check="route-missing-error-responses",
                        severity="error",
                        message="Route has no error responses (4xx or 5xx).",
                        suggestion=(
                            "Add responses for at least: "
                            "400 (validation), 401 (auth). "
                            "Set auth to required/optional/none."
                        ),
                    )
                )

        # Check for auth field
        if "auth" not in data:
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="route-missing-auth",
                    severity="error",
                    message="Route is missing the 'auth' field.",
                    suggestion=(
                        "Add responses for at least: 400 (validation), 401 (auth). Set auth to required/optional/none."
                    ),
                )
            )

        return findings

    # -- NFR checks --

    def _check_nfr(self, component_id: str, file_path: str, data: dict[str, Any]) -> list[ComponentFinding]:
        findings: list[ComponentFinding] = []
        if self._get_component_type(component_id) != "nfr":
            return findings

        target = data.get("target")
        if target is not None and not isinstance(target, (int, float)):
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="nfr-non-numeric-target",
                    severity="error",
                    message=f"NFR target is not numeric: '{target}'.",
                    suggestion="Change target to a number and add unit. Example: target: 200, unit: ms",
                )
            )
        elif target is None:
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="nfr-missing-target",
                    severity="error",
                    message="NFR is missing a numeric 'target' field.",
                    suggestion="Change target to a number and add unit. Example: target: 200, unit: ms",
                )
            )

        if "unit" not in data:
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="nfr-missing-unit",
                    severity="warning",
                    message="NFR is missing a 'unit' field.",
                    suggestion="Change target to a number and add unit. Example: target: 200, unit: ms",
                )
            )

        return findings

    # -- Entity checks --

    def _check_entity(self, component_id: str, file_path: str, data: dict[str, Any]) -> list[ComponentFinding]:
        findings: list[ComponentFinding] = []
        if self._get_component_type(component_id) != "entity":
            return findings

        states = data.get("states")
        transitions = data.get("transitions")

        if states and not transitions:
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="entity-states-without-transitions",
                    severity="error",
                    message="Entity defines 'states' but no 'transitions'.",
                    suggestion=("Add a 'transitions' field listing from/to pairs for each state change."),
                )
            )
        elif states and transitions and isinstance(states, list) and isinstance(transitions, list):
            # Check for unreachable states
            reachable: set[str] = set()
            for t in transitions:
                if isinstance(t, dict):
                    if "from" in t:
                        reachable.add(str(t["from"]))
                    if "to" in t:
                        reachable.add(str(t["to"]))

            for state in states:
                state_name = str(state)
                if state_name not in reachable:
                    findings.append(
                        ComponentFinding(
                            component_id=component_id,
                            file_path=file_path,
                            check="entity-unreachable-state",
                            severity="warning",
                            message=f"State '{state_name}' is unreachable — no transition leads to or from it.",
                            suggestion=(
                                f"State '{state_name}' is unreachable — no transition leads to it. "
                                "Add a transition or remove the state."
                            ),
                        )
                    )

        return findings

    # -- Naming checks --

    def _check_naming(self, component_id: str, file_path: str, data: dict[str, Any]) -> list[ComponentFinding]:
        findings: list[ComponentFinding] = []
        comp_type = self._get_component_type(component_id)
        name = self._get_component_name(component_id)

        if not name:
            return findings

        if comp_type in _PASCAL_TYPES and not _PASCAL_CASE_RE.match(name):
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="naming-not-pascal-case",
                    severity="warning",
                    message=f"Entity name '{name}' is not PascalCase.",
                    suggestion=f"Rename '{name}' to PascalCase (e.g. 'Order', 'UserProfile').",
                )
            )

        if comp_type in _KEBAB_TYPES and not _KEBAB_CASE_RE.match(name):
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="naming-not-kebab-case",
                    severity="warning",
                    message=f"{comp_type.capitalize()} name '{name}' is not kebab-case.",
                    suggestion=f"Rename '{name}' to kebab-case (e.g. 'create-order', 'validate-balance').",
                )
            )

        return findings

    # -- Description checks --

    def _check_description(self, component_id: str, file_path: str, data: dict[str, Any]) -> list[ComponentFinding]:
        findings: list[ComponentFinding] = []
        description = data.get("description", "")

        if not description or not str(description).strip():
            findings.append(
                ComponentFinding(
                    component_id=component_id,
                    file_path=file_path,
                    check="missing-description",
                    severity="warning",
                    message="Component has no description.",
                    suggestion="Add a non-empty 'description' field explaining this component's purpose.",
                )
            )

        return findings
