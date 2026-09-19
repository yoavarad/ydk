"""Tests for the baseline solution/project scaffold generators in the
dotnet-webapi-clean ignition pack (solution-scaffold, program-and-config).

Scope: only the generators, _context modules, and templates this task
produces. Full-pack structural/e2e testing (all 13 generators, samples,
templates dirs) is out of scope here -- see the pack's downstream tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"
GENERATORS_DIR = PACK_ROOT / "generators"

BASELINE_GENERATOR_IDS = {"solution-scaffold", "program-and-config"}


def _run_generator(script_name: str) -> list[dict]:
    """Run a generator script exactly as IgnitionEngine._run_generator does:
    `sys.executable <script>`, stdout must be a single JSON array."""
    script_path = GENERATORS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"{script_name} failed: {result.stderr}"
    assert result.stderr.strip() == "", f"{script_name} wrote to stderr: {result.stderr}"
    stdout = result.stdout.strip()
    data = json.loads(stdout)
    assert isinstance(data, list)
    for item in data:
        assert set(item.keys()) == {"path", "content"}
    return data


class TestContextModules:
    """Shared _context utilities must be present."""

    REQUIRED_CONTEXT: ClassVar[list[str]] = ["__init__.py", "naming.py", "types.py", "imports.py"]

    @pytest.mark.parametrize("filename", REQUIRED_CONTEXT)
    def test_context_module_exists(self, filename: str) -> None:
        assert (GENERATORS_DIR / "_context" / filename).is_file(), f"Missing context module: {filename}"


class TestManifestAlignment:
    """The generator scripts this task builds must match manifest.yaml exactly."""

    def test_baseline_generator_scripts_exist(self) -> None:
        manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
        generators = {g["id"]: g for g in manifest["generators"]}
        for gen_id in BASELINE_GENERATOR_IDS:
            assert gen_id in generators, f"manifest.yaml missing generator id: {gen_id}"
            script_path = PACK_ROOT / generators[gen_id]["script"]
            assert script_path.is_file(), f"Generator script missing: {generators[gen_id]['script']}"
            assert generators[gen_id]["inputs"] == []


# _context is a plain sibling package next to the generator scripts (not pip
# installed), so import it the same way the generator scripts do: add
# GENERATORS_DIR to sys.path and import `_context.<module>` as a real package
# (needed since naming.py does `from .types import ...` internally).
if str(GENERATORS_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATORS_DIR))


def _load_naming_module():
    import _context.naming as naming

    return naming


def _load_types_module():
    import _context.types as types_mod

    return types_mod


def _load_imports_module():
    import _context.imports as imports_mod

    return imports_mod


class TestNamingHelpers:
    def test_to_pascal(self) -> None:
        naming = _load_naming_module()
        assert naming.to_pascal("strategy_run") == "StrategyRun"
        assert naming.to_pascal("strategy-run") == "StrategyRun"
        assert naming.to_pascal("strategyRun") == "StrategyRun"
        assert naming.to_pascal("StrategyRun") == "StrategyRun"

    def test_to_camel(self) -> None:
        naming = _load_naming_module()
        assert naming.to_camel("StrategyRun") == "strategyRun"
        assert naming.to_camel("strategy_run") == "strategyRun"

    def test_derive_name_from_ydk_id(self) -> None:
        naming = _load_naming_module()
        assert naming.derive_name({"id": "ydk:entity:strategy/Strategy"}) == "Strategy"
        assert naming.derive_name({"id": "ydk:contract:strategy/StrategyService"}) == "StrategyService"
        assert naming.derive_name({"name": "legacy_name"}) == "LegacyName"

    def test_derive_table_name_pluralizes(self) -> None:
        naming = _load_naming_module()
        assert naming.derive_table_name({"id": "ydk:entity:item/Item"}) == "Items"
        assert naming.derive_table_name({"id": "ydk:entity:category/Category"}) == "Categories"
        assert naming.derive_table_name({"table_name": "custom_items"}) == "custom_items"

    def test_pk_type_default(self) -> None:
        naming = _load_naming_module()
        assert naming.pk_type({}) == "int"
        entity = {"fields": {"id": {"type": "uuid", "primary_key": True}}}
        assert naming.pk_type(entity) == "Guid"

    def test_iter_fields(self) -> None:
        naming = _load_naming_module()
        entity = {"fields": {"name": {"type": "string"}}}
        assert list(naming.iter_fields(entity)) == [("name", {"type": "string"})]


class TestTypes:
    def test_canonical_to_csharp_mapping(self) -> None:
        types_mod = _load_types_module()
        assert types_mod.CANONICAL_TO_CSHARP["string"] == "string"
        assert types_mod.CANONICAL_TO_CSHARP["uuid"] == "Guid"
        assert types_mod.CANONICAL_TO_CSHARP["decimal"] == "decimal"
        assert types_mod.CANONICAL_TO_CSHARP["datetime"] == "DateTime"
        assert types_mod.CANONICAL_TO_CSHARP["optional[string]"] == "string?"


class TestImports:
    def test_sort_usings_system_first(self) -> None:
        imports_mod = _load_imports_module()
        result = imports_mod.sort_usings({"MyApp.Domain", "System.Collections.Generic", "System"})
        assert result == ["System", "System.Collections.Generic", "MyApp.Domain"]

    def test_format_using_block(self) -> None:
        imports_mod = _load_imports_module()
        block = imports_mod.format_using_block({"System", "MyApp.Domain"})
        assert block == "using System;\n\nusing MyApp.Domain;"

    def test_format_using_block_empty(self) -> None:
        imports_mod = _load_imports_module()
        assert imports_mod.format_using_block([]) == ""


class TestSolutionScaffoldGenerator:
    """generators/solution_scaffold.py (inputs: [])."""

    def test_emits_expected_paths(self) -> None:
        files = _run_generator("solution_scaffold.py")
        paths = {f["path"] for f in files}
        assert "WebApiClean.sln" in paths
        assert ".editorconfig" in paths
        assert "Directory.Build.props" in paths
        assert "Domain/WebApiClean.Domain.csproj" in paths
        assert "Application/WebApiClean.Application.csproj" in paths
        assert "Infrastructure/WebApiClean.Infrastructure.csproj" in paths
        assert "Api/WebApiClean.Api.csproj" in paths
        assert "WebApiClean.Tests/WebApiClean.Tests.csproj" in paths

    def test_sln_references_all_projects(self) -> None:
        files = _run_generator("solution_scaffold.py")
        sln = next(f["content"] for f in files if f["path"] == "WebApiClean.sln")
        for name in ["Domain", "Application", "Infrastructure", "Api", "Tests"]:
            assert f"WebApiClean.{name}" in sln

    def test_directory_build_props_targets_net8(self) -> None:
        files = _run_generator("solution_scaffold.py")
        props = next(f["content"] for f in files if f["path"] == "Directory.Build.props")
        assert "<TargetFramework>net8.0</TargetFramework>" in props

    def test_infrastructure_references_sqlite(self) -> None:
        files = _run_generator("solution_scaffold.py")
        infra_csproj = next(
            f["content"] for f in files if f["path"] == "Infrastructure/WebApiClean.Infrastructure.csproj"
        )
        assert "Microsoft.EntityFrameworkCore.Sqlite" in infra_csproj

    def test_generation_is_deterministic(self) -> None:
        """Re-running the generator must produce byte-identical output (stable GUIDs)."""
        first = _run_generator("solution_scaffold.py")
        second = _run_generator("solution_scaffold.py")
        assert first == second


class TestProgramAndConfigGenerator:
    """generators/program_and_config.py (inputs: [])."""

    def test_emits_expected_paths(self) -> None:
        files = _run_generator("program_and_config.py")
        paths = {f["path"] for f in files}
        assert paths == {
            "Api/Program.cs",
            "Api/appsettings.json",
            "Api/appsettings.Development.json",
            "Api/Properties/launchSettings.json",
        }

    def test_program_cs_has_minimal_api_bootstrap(self) -> None:
        files = _run_generator("program_and_config.py")
        program_cs = next(f["content"] for f in files if f["path"] == "Api/Program.cs")
        assert "WebApplication.CreateBuilder" in program_cs
        assert "app.Run()" in program_cs

    def test_program_cs_wires_di_and_generated_endpoints(self) -> None:
        """Program.cs must unconditionally call the DI and endpoint-registration
        extensions generators/dependency_injection.py and generators/api_endpoints.py
        always emit, so a generated API actually serves generated routes and
        resolves generated services (#127)."""
        files = _run_generator("program_and_config.py")
        program_cs = next(f["content"] for f in files if f["path"] == "Api/Program.cs")
        assert "using Api;" in program_cs
        assert "using Api.Endpoints;" in program_cs
        assert "builder.Services.AddApplicationServices(builder.Configuration);" in program_cs
        assert "app.MapGeneratedEndpoints();" in program_cs

    def test_program_cs_has_no_stale_downstream_generator_todo(self) -> None:
        files = _run_generator("program_and_config.py")
        program_cs = next(f["content"] for f in files if f["path"] == "Api/Program.cs")
        assert "TODO" not in program_cs

    def test_appsettings_are_valid_json(self) -> None:
        files = _run_generator("program_and_config.py")
        for path in ("Api/appsettings.json", "Api/appsettings.Development.json"):
            content = next(f["content"] for f in files if f["path"] == path)
            json.loads(content)  # must not raise

    def test_launch_settings_is_valid_json(self) -> None:
        files = _run_generator("program_and_config.py")
        content = next(f["content"] for f in files if f["path"] == "Api/Properties/launchSettings.json")
        json.loads(content)  # must not raise
