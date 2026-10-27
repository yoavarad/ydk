"""Predefined technology stacks for ``ydk init --stack``."""

from __future__ import annotations

from typing import Any

STACKS: dict[str, dict[str, Any]] = {
    "python-fastapi": {
        "verifications": [
            "lint-ruff",
            "types-ty",
            "tests-pytest",
            "python-quality",
            "python-no-future-annotations",
            "python-file-length",
            "python-tdd-guard",
            "fastapi-route-delegation",
            "fastapi-adapter-isolation",
            "fastapi-core-purity",
            "fastapi-service-sync",
            "fastapi-route-splitting",
            "fastapi-no-mocks-e2e",
            "fastapi-no-mocks-integration",
        ],
        "templates": ["fastapi-protocol-hexagonal"],
        "config_overrides": {
            "spec_check.thresholds.completeness": 8,
            "spec_check.thresholds.architecture": 8,
        },
    },
    "python-cli": {
        "verifications": [
            "lint-ruff",
            "types-ty",
            "tests-pytest",
            "python-quality",
            "cli-error-handling",
            "cli-output-format",
        ],
        "templates": ["python-typer-cli"],
    },
    "python-cli-basic": {
        "verifications": [
            "lint-ruff",
            "types-ty",
            "tests-pytest",
            "python-quality",
        ],
    },
    "nextjs-fsd": {
        "verifications": [
            "nextjs-fsd-imports",
            "nextjs-fsd-layers",
            "nextjs-page-purity",
            "nextjs-server-client-boundary",
            "nextjs-no-direct-env",
            "nextjs-no-direct-fetch",
            "nextjs-file-sizes",
        ],
        "templates": ["nextjs-fsd-shadcn"],
    },
    "terraform": {
        "verifications": [
            "terraform-format",
            "terraform-security",
            "terraform-tagging",
            "terraform-dangling-resources",
        ],
    },
    "dotnet": {
        "verifications": [
            "dotnet-build",
            "dotnet-format",
            "dotnet-test",
            "dotnet-tdd-guard",
        ],
        "templates": ["dotnet-webapi-clean"],
    },
    "go": {
        "verifications": [
            "go-fmt",
            "go-vet",
            "go-test",
            "go-vendor",
            "helm-lint",
            "spec-alignment",
            "pr-body-validation",
            "ai-code-review",
            "tdd-guard",
            "tdd-guard-cmd",
            "guard-no-manual-pr",
            "guard-no-noqa",
            "guard-no-proof-tamper",
            "guard-stage-gate",
            "guard-stage-gate-cmd",
        ],
        "config_overrides": {
            "verification.tdd.source_globs": ["**/*.go"],
            "verification.tdd.test_globs": ["**/*_test.go"],
            "verification.tdd.exempt_globs": ["vendor/**", "test/**"],
            "verification.tdd.test_for": "same-dir-suffix",
            "verification.tdd.test_suffix": "_test.go",
            "tdd.test_commands": [r"\bgo test\b", r"\bmake test\b"],
            "guards.code_dirs": ["cmd", "internal", "pkg", "charts", "scripts", "test", "tests"],
            "testing.test_globs": ["**/*_test.go"],
        },
    },
}


def get_stack(name: str) -> dict[str, Any]:
    """Return stack definition or raise ``KeyError``."""
    if name not in STACKS:
        msg = f"Unknown stack: {name!r}. Available: {', '.join(sorted(STACKS))}"
        raise KeyError(msg)
    return STACKS[name]
