"""Unit tests for the dotnet-webapi-clean pack's test-stub generators:
fake_repositories.py, unit_test_stubs.py, endpoint_test_stubs.py, and
entity_test_stubs.py.

Each generator is invoked exactly as the ignition engine invokes it (subprocess,
component YAML paths via YDK_COMPONENTS_<TYPE> env vars, JSON array on stdout)
so these tests exercise the real generator contract, not just internal helpers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"
GENERATORS_DIR = PACK_ROOT / "generators"

SAMPLE_ENTITY = {
    "id": "ydk:entity:orders/Order",
    "description": "An order placed by a customer",
    "fields": {
        "id": {"type": "uuid", "primary_key": True, "description": "Unique identifier"},
        "customer_name": {"type": "string", "required": True, "description": "Customer name"},
        "total": {"type": "decimal", "description": "Order total"},
    },
}

SAMPLE_CONTRACT = {
    "id": "ydk:contract:orders/OrderService",
    "description": "Order service contract",
    "methods": {
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
        "create_order": {
            "description": "Create a new order",
            "params": {"total": {"type": "decimal"}},
            "returns": {"type": "Order"},
        },
    },
}

SAMPLE_ROUTES = [
    {"id": "ydk:route:orders/list", "method": "GET", "path": "/orders", "tag": "orders"},
    {"id": "ydk:route:orders/get", "method": "GET", "path": "/orders/{order_id}", "tag": "orders"},
    {"id": "ydk:route:orders/create", "method": "POST", "path": "/orders", "tag": "orders"},
]


def _write_component_yaml(tmp_path: Path, name: str, components: list[dict]) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.dump(components, default_flow_style=False), encoding="utf-8")
    return path


def _run_generator(script: str, env_extra: dict[str, str]) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(GENERATORS_DIR / script)],
        capture_output=True,
        text=True,
        env={**os.environ, **env_extra},
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"{script} failed: {result.stderr}"
    return json.loads(result.stdout.strip())


@pytest.fixture
def entity_env(tmp_path: Path) -> dict[str, str]:
    entity_path = _write_component_yaml(tmp_path, "entity", [SAMPLE_ENTITY])
    return {"YDK_COMPONENTS_ENTITY": str(entity_path)}


@pytest.fixture
def contract_and_entity_env(tmp_path: Path) -> dict[str, str]:
    contract_path = _write_component_yaml(tmp_path, "contract", [SAMPLE_CONTRACT])
    entity_path = _write_component_yaml(tmp_path, "entity", [SAMPLE_ENTITY])
    return {"YDK_COMPONENTS_CONTRACT": str(contract_path), "YDK_COMPONENTS_ENTITY": str(entity_path)}


@pytest.fixture
def route_env(tmp_path: Path) -> dict[str, str]:
    route_path = _write_component_yaml(tmp_path, "route", SAMPLE_ROUTES)
    return {"YDK_COMPONENTS_ROUTE": str(route_path)}


class TestManifestAlignment:
    """This task's four generator scripts must match manifest.yaml exactly."""

    IDS: tuple[str, ...] = (
        "fake-repositories",
        "unit-test-stubs",
        "endpoint-test-stubs",
        "entity-test-stubs",
    )

    def test_generator_scripts_declared_and_exist(self) -> None:
        manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text())
        generators = {g["id"]: g for g in manifest["generators"]}
        for gen_id in self.IDS:
            assert gen_id in generators, f"manifest.yaml missing generator id: {gen_id}"
            script_path = PACK_ROOT / generators[gen_id]["script"]
            assert script_path.is_file(), f"Generator script missing: {generators[gen_id]['script']}"


class TestFakeRepositories:
    def test_emits_fake_for_entity(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("fake_repositories.py", entity_env)
        assert len(files) == 1
        assert files[0]["path"] == "WebApiClean.Tests/Fakes/FakeOrderRepository.cs"

    def test_fake_implements_repository_interface_with_dictionary(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("fake_repositories.py", entity_env)
        content = files[0]["content"]
        assert "namespace Tests.Fakes;" in content
        assert "public class FakeOrderRepository : IOrderRepository" in content
        assert "Dictionary<Guid, Order> _items" in content
        assert "Task<Order?> GetByIdAsync(Guid id)" in content
        assert "Task<IEnumerable<Order>> ListAsync()" in content
        assert "Task<Order> AddAsync(Order entity)" in content
        assert "Task UpdateAsync(Order entity)" in content
        assert "Task DeleteAsync(Guid id)" in content

    def test_empty_entities_emits_no_files(self, tmp_path: Path) -> None:
        env = {"YDK_COMPONENTS_ENTITY": str(_write_component_yaml(tmp_path, "entity", []))}
        assert _run_generator("fake_repositories.py", env) == []


class TestUnitTestStubs:
    def test_emits_test_class_for_contract(self, contract_and_entity_env: dict[str, str]) -> None:
        files = _run_generator("unit_test_stubs.py", contract_and_entity_env)
        assert len(files) == 1
        assert files[0]["path"] == "WebApiClean.Tests/Services/OrderServiceTests.cs"

    def test_one_fact_per_contract_method(self, contract_and_entity_env: dict[str, str]) -> None:
        files = _run_generator("unit_test_stubs.py", contract_and_entity_env)
        content = files[0]["content"]
        assert content.count("[Fact]") == 3
        for method in ("GetOrder", "ListOrders", "CreateOrder"):
            assert f"public async Task {method}_ThrowsNotImplemented()" in content

    def test_uses_fake_repository_and_asserts_current_stub_behavior(
        self, contract_and_entity_env: dict[str, str]
    ) -> None:
        files = _run_generator("unit_test_stubs.py", contract_and_entity_env)
        content = files[0]["content"]
        assert "namespace Tests.Services;" in content
        assert "using Tests.Fakes;" in content
        assert "var orderRepository = new FakeOrderRepository();" in content
        assert "var service = new OrderService(orderRepository);" in content
        assert "Assert.ThrowsAsync<NotImplementedException>" in content


class TestEndpointTestStubs:
    def test_emits_test_class_per_tag(self, route_env: dict[str, str]) -> None:
        files = _run_generator("endpoint_test_stubs.py", route_env)
        assert len(files) == 1
        assert files[0]["path"] == "WebApiClean.Tests/Endpoints/OrdersEndpointsTests.cs"

    def test_one_fact_per_route(self, route_env: dict[str, str]) -> None:
        files = _run_generator("endpoint_test_stubs.py", route_env)
        content = files[0]["content"]
        assert content.count("[Fact]") == len(SAMPLE_ROUTES)

    def test_uses_webapplicationfactory_and_substitutes_path_params(self, route_env: dict[str, str]) -> None:
        files = _run_generator("endpoint_test_stubs.py", route_env)
        content = files[0]["content"]
        assert "namespace Tests.Endpoints;" in content
        assert "IClassFixture<WebApplicationFactory<Program>>" in content
        assert "_factory.CreateClient()" in content
        assert 'await client.GetAsync("/orders")' in content
        assert 'await client.GetAsync("/orders/1")' in content
        assert 'await client.PostAsync("/orders", content)' in content

    def test_empty_routes_emits_no_files(self, tmp_path: Path) -> None:
        env = {"YDK_COMPONENTS_ROUTE": str(_write_component_yaml(tmp_path, "route", []))}
        assert _run_generator("endpoint_test_stubs.py", env) == []


class TestEntityTestStubs:
    def test_emits_test_for_entity(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("entity_test_stubs.py", entity_env)
        assert len(files) == 1
        assert files[0]["path"] == "WebApiClean.Tests/Domain/OrderTests.cs"

    def test_namespace_does_not_collide_with_domain_entities(self, entity_env: dict[str, str]) -> None:
        """Regression test: `namespace Tests.Domain;` would shadow the real
        `Domain` root namespace for every file in the Tests project (C#
        resolves `using Domain.Entities;` against the closest enclosing
        `Domain` segment first), breaking `using Domain.Entities;` compilation
        across the whole test assembly. Verified with a real `dotnet build`.
        """
        files = _run_generator("entity_test_stubs.py", entity_env)
        content = files[0]["content"]
        assert "namespace Tests.EntityTests;" in content
        assert "namespace Tests.Domain;" not in content

    def test_each_sample_value_captured_once_to_avoid_double_evaluation(self, entity_env: dict[str, str]) -> None:
        """Regression test: assigning `entity.Id = Guid.NewGuid();` and then
        asserting `Assert.Equal(Guid.NewGuid(), entity.Id)` would evaluate
        Guid.NewGuid() twice, producing two different values and failing
        nondeterministically. Each sample value must be captured in a local
        variable and reused for both the assignment and the assertion.
        """
        files = _run_generator("entity_test_stubs.py", entity_env)
        content = files[0]["content"]
        assert "var idValue = Guid.NewGuid();" in content
        assert "entity.Id = idValue;" in content
        assert "Assert.Equal(idValue, entity.Id);" in content
        assert content.count("Guid.NewGuid()") == 1

    def test_empty_entities_emits_no_files(self, tmp_path: Path) -> None:
        env = {"YDK_COMPONENTS_ENTITY": str(_write_component_yaml(tmp_path, "entity", []))}
        assert _run_generator("entity_test_stubs.py", env) == []
