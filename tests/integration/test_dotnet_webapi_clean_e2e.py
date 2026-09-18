"""End-to-end regression test for the dotnet-webapi-clean generator pack.

Task #124's bug (path-prefix mismatch + namespace mismatch across generators)
was found via a real `dotnet build`/`dotnet test` against ignited output --
per-generator unit tests alone did not catch it, because they assert each
generator's own output in isolation and never materialize the full solution
on disk. This test runs the FULL generator pipeline (via the real
IgnitionEngine, exactly as `ydk ignite` does) against a sample
entity+contract+route, then builds and tests the result for real.

No `samples/components/` fixtures exist yet for this pack (populating them is
task #108, blocked on this fix) -- the sample entity/contract/route below are
defined inline for this test only, mirroring the shape used by
tests/catalog/test_dotnet_webapi_clean_api_generators.py's SAMPLE_ENTITY/
SAMPLE_CONTRACT/SAMPLE_ROUTES.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from ydk.models.ignition import IgnitionResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"

PROJECT_DIRS = ("Domain", "Application", "Infrastructure", "Api", "WebApiClean.Tests")

SAMPLE_ENTITY = {
    "$schema": "ydk:schema:entity",
    "id": "ydk:entity:orders/Order",
    "description": "An order placed by a customer",
    "table_name": "orders",
    "fields": {
        "id": {"type": "uuid", "primary_key": True, "description": "Unique identifier"},
        "customer_name": {"type": "string", "required": True, "max_length": 200, "description": "Customer name"},
        "total": {"type": "decimal", "required": True, "precision": [10, 2], "description": "Order total"},
        "is_paid": {"type": "boolean", "required": True, "description": "Payment status"},
        "created_at": {"type": "datetime", "required": True, "description": "Creation time"},
        "notes": {"type": "text", "required": False, "nullable": True, "description": "Optional notes"},
    },
}

SAMPLE_CONTRACT = {
    "$schema": "ydk:schema:contract",
    "id": "ydk:contract:orders/OrderService",
    "description": "Order service contract",
    "methods": {
        "create_order": {
            "description": "Create a new order",
            "params": {
                "customer_name": {"type": "string"},
                "total": {"type": "decimal"},
                "is_paid": {"type": "boolean"},
            },
            "returns": {"type": "Order"},
        },
        "get_order": {
            "description": "Get an order by id",
            "params": {"order_id": {"type": "uuid"}},
            "returns": {"type": "Optional[Order]"},
        },
        "list_orders": {
            "description": "List all orders",
            "params": {},
            "returns": {"type": "list[Order]"},
        },
    },
}

SAMPLE_ROUTES = [
    {
        "$schema": "ydk:schema:route",
        "id": "ydk:route:orders/create",
        "method": "POST",
        "path": "/orders",
        "tag": "orders",
        "maps_to_use_case": "OrderService.create_order",
        "request": {
            "body": {
                "customer_name": {"type": "string", "required": True},
                "total": {"type": "decimal", "required": True},
                "is_paid": {"type": "boolean", "required": True},
            }
        },
        "responses": {"success": {"status": 201}},
    },
    {
        "$schema": "ydk:schema:route",
        "id": "ydk:route:orders/list",
        "method": "GET",
        "path": "/orders",
        "tag": "orders",
        "maps_to_use_case": "OrderService.list_orders",
        "responses": {"success": {"status": 200}},
    },
    {
        "$schema": "ydk:schema:route",
        "id": "ydk:route:orders/get",
        "method": "GET",
        "path": "/orders/{order_id}",
        "tag": "orders",
        "maps_to_use_case": "OrderService.get_order",
        "request": {"path_params": {"order_id": {"type": "uuid"}}},
        "responses": {"success": {"status": 200}},
    },
]


def _dotnet_available() -> bool:
    """True when a real .NET SDK (not just a bare muxer) is on PATH."""
    dotnet = shutil.which("dotnet")
    if not dotnet:
        return False
    try:
        result = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


@pytest.fixture(scope="module")
def generated_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the real IgnitionEngine (all 13 generators, in manifest order) against
    the sample entity+contract+route, exactly as `ydk ignite` would."""
    project = tmp_path_factory.mktemp("dotnet_webapi_clean_e2e")

    pack_dest = project / ".ydk" / "ignition-packs" / "dotnet-webapi-clean"
    pack_dest.mkdir(parents=True)
    shutil.copytree(PACK_DIR / "generators", pack_dest / "generators")
    shutil.copytree(PACK_DIR / "templates", pack_dest / "templates")
    shutil.copy(PACK_DIR / "manifest.yaml", pack_dest / "manifest.yaml")

    components_dest = project / ".ydk" / "components"
    (components_dest / "entity" / "sample").mkdir(parents=True)
    (components_dest / "contract" / "sample").mkdir(parents=True)
    (components_dest / "route" / "sample").mkdir(parents=True)
    (components_dest / "entity" / "sample" / "Order.yaml").write_text(yaml.dump(SAMPLE_ENTITY))
    (components_dest / "contract" / "sample" / "OrderService.yaml").write_text(yaml.dump(SAMPLE_CONTRACT))
    for route in SAMPLE_ROUTES:
        name = route["id"].rsplit("/", 1)[1]
        (components_dest / "route" / "sample" / f"{name}.yaml").write_text(yaml.dump(route))

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from ydk.core.ignition import IgnitionEngine

    engine = IgnitionEngine(project)
    result: IgnitionResult = engine.ignite(dry_run=False)

    assert result.errors == [], f"Ignition errors: {result.errors}"
    assert result.files_generated > 10, f"Only {result.files_generated} files generated"

    return project


class TestGeneratedLayout:
    """Structural checks that don't need the .NET SDK -- guard against the
    path-prefix regression (#124) independently of dotnet availability."""

    def test_all_project_directories_created(self, generated_project: Path) -> None:
        for project_dir in PROJECT_DIRS:
            assert (generated_project / project_dir).is_dir(), f"Missing project directory: {project_dir}"

    def test_every_generated_cs_file_is_under_a_project_directory(self, generated_project: Path) -> None:
        """Every .cs file must live under one of the 5 project directories so it
        falls inside that project's default SDK-style compile glob -- a file
        written outside all of them (like the pre-fix `Domain/Entities/*.cs`
        landing next to, not inside, `Domain/`) would silently not compile."""
        cs_files = list(generated_project.rglob("*.cs"))
        assert len(cs_files) > 5, "Expected multiple generated .cs files"
        for f in cs_files:
            rel = f.relative_to(generated_project)
            assert rel.parts[0] in PROJECT_DIRS, f"{rel} is not under a scaffolded project directory"

    def test_solution_file_references_every_project(self, generated_project: Path) -> None:
        sln = (generated_project / "WebApiClean.sln").read_text().replace("\\", "/")
        for project_dir in PROJECT_DIRS:
            assert f'"{project_dir}/WebApiClean' in sln, f"{project_dir} project missing from .sln"


@pytest.mark.integration
@pytest.mark.skipif(not _dotnet_available(), reason=".NET SDK not available")
class TestDotnetBuildAndTest:
    """Acceptance criteria from issue #124: a real `dotnet build` must succeed
    with 0 errors, and `dotnet test` must run against the generated output."""

    def test_dotnet_build_succeeds(self, generated_project: Path) -> None:
        result = subprocess.run(
            ["dotnet", "build", str(generated_project / "WebApiClean.sln"), "--nologo"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, (
            f"dotnet build failed (exit {result.returncode}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "error" not in result.stdout.lower() or "0 error" in result.stdout.lower()

    def test_dotnet_test_succeeds(self, generated_project: Path) -> None:
        result = subprocess.run(
            ["dotnet", "test", str(generated_project / "WebApiClean.sln"), "--nologo"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, (
            f"dotnet test failed (exit {result.returncode}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
