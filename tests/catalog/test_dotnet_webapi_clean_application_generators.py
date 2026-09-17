"""Unit tests for the dotnet-webapi-clean pack's Application-layer generators:
repository_interfaces.py, repository_implementations.py, and service_stubs.py.

Each generator is invoked exactly as the ignition engine invokes it (subprocess,
component YAML paths via YDK_COMPONENTS_<TYPE> env vars, JSON array on stdout)
so these tests exercise the real generator contract, not just internal helpers.
"""

from __future__ import annotations

import json
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
            "returns": {"type": "Order"},
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


def _write_component_yaml(tmp_path: Path, name: str, components: list[dict]) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.dump(components, default_flow_style=False), encoding="utf-8")
    return path


def _run_generator(script: str, env_extra: dict[str, str]) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(GENERATORS_DIR / script)],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **env_extra},
        timeout=30,
    )
    assert result.returncode == 0, f"{script} failed: {result.stderr}"
    return json.loads(result.stdout.strip())


@pytest.fixture
def entity_env(tmp_path: Path) -> dict[str, str]:
    entity_path = _write_component_yaml(tmp_path, "entity", [SAMPLE_ENTITY])
    return {"YDK_COMPONENTS_ENTITY": str(entity_path)}


@pytest.fixture
def contract_env(tmp_path: Path) -> dict[str, str]:
    contract_path = _write_component_yaml(tmp_path, "contract", [SAMPLE_CONTRACT])
    return {"YDK_COMPONENTS_CONTRACT": str(contract_path)}


class TestRepositoryInterfaces:
    def test_emits_interface_for_entity(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("repository_interfaces.py", entity_env)
        assert len(files) == 1
        assert files[0]["path"] == "Application/Interfaces/IOrderRepository.cs"

    def test_interface_has_crud_signatures(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("repository_interfaces.py", entity_env)
        content = files[0]["content"]
        assert "public interface IOrderRepository" in content
        assert "Task<Order?> GetByIdAsync(Guid id);" in content
        assert "Task<IEnumerable<Order>> ListAsync();" in content
        assert "Task<Order> AddAsync(Order entity);" in content
        assert "Task UpdateAsync(Order entity);" in content
        assert "Task DeleteAsync(Guid id);" in content


class TestRepositoryImplementations:
    def test_emits_impl_for_entity(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("repository_implementations.py", entity_env)
        assert len(files) == 1
        assert files[0]["path"] == "Infrastructure/Persistence/Repositories/OrderRepository.cs"

    def test_impl_uses_dbcontext_and_dbset(self, entity_env: dict[str, str]) -> None:
        files = _run_generator("repository_implementations.py", entity_env)
        content = files[0]["content"]
        assert "public class OrderRepository : IOrderRepository" in content
        assert "private readonly AppDbContext _context;" in content
        assert "public OrderRepository(AppDbContext context)" in content
        assert "_context.Orders" in content
        assert "await _context.SaveChangesAsync();" in content


class TestServiceStubs:
    def test_emits_interface_and_class_for_contract(self, contract_env: dict[str, str]) -> None:
        files = _run_generator("service_stubs.py", contract_env)
        paths = {f["path"] for f in files}
        assert paths == {
            "Application/Services/IOrderService.cs",
            "Application/Services/OrderService.cs",
        }

    def test_class_implements_interface_and_injects_repository(self, contract_env: dict[str, str]) -> None:
        files = _run_generator("service_stubs.py", contract_env)
        stub = next(f for f in files if f["path"] == "Application/Services/OrderService.cs")["content"]
        assert "public class OrderService : IOrderService" in stub
        assert "private readonly IOrderRepository _orderRepository;" in stub
        assert "public OrderService(IOrderRepository orderRepository)" in stub

    def test_method_bodies_use_exact_not_implemented_string(self, contract_env: dict[str, str]) -> None:
        files = _run_generator("service_stubs.py", contract_env)
        stub = next(f for f in files if f["path"] == "Application/Services/OrderService.cs")["content"]
        # This exact string is what IgnitionEngine._register_todos scans for.
        for line in stub.splitlines():
            if "NotImplementedException" in line:
                assert line.strip() == "throw new NotImplementedException();"
        assert stub.count("throw new NotImplementedException();") == 3

    def test_method_signatures_map_types_and_names(self, contract_env: dict[str, str]) -> None:
        files = _run_generator("service_stubs.py", contract_env)
        interface = next(f for f in files if f["path"] == "Application/Services/IOrderService.cs")["content"]
        assert "Task<Order> GetOrder(Guid orderId);" in interface
        assert "Task<IEnumerable<Order>> ListOrders();" in interface
        assert "Task<Order> CreateOrder(decimal total);" in interface
