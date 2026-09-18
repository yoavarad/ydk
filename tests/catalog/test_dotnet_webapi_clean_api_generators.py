"""Unit tests for the dotnet-webapi-clean pack's Api-layer generators:
api_endpoints.py and dependency_injection.py.

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
        "cancel_order": {
            "description": "Cancel an order",
            "params": {"order_id": {"type": "uuid"}, "reason": {"type": "string"}},
            "returns": {"type": "void"},
        },
    },
}

SAMPLE_ROUTES = [
    {
        "id": "ydk:route:orders/list",
        "method": "GET",
        "path": "/orders",
        "maps_to_use_case": "OrderService.list_orders",
        "responses": {200: {"description": "ok"}},
    },
    {
        "id": "ydk:route:orders/get",
        "method": "GET",
        "path": "/orders/{order_id}",
        "maps_to_use_case": "OrderService.get_order",
        "request": {"path_params": {"order_id": {"type": "uuid"}}},
        "responses": {200: {"description": "ok"}},
    },
    {
        "id": "ydk:route:orders/create",
        "method": "POST",
        "path": "/orders",
        "maps_to_use_case": "OrderService.create_order",
        "request": {"body": {"total": {"type": "decimal", "required": True}}},
        "responses": {201: {"description": "created"}},
    },
    {
        "id": "ydk:route:orders/cancel",
        "method": "POST",
        "path": "/orders/{id}/cancel",
        "maps_to_use_case": "OrderService.cancel_order",
        "responses": {204: {"description": "cancelled"}},
    },
]


def _write_component_yaml(tmp_path: Path, name: str, components: list[dict]) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.dump(components, default_flow_style=False), encoding="utf-8")
    return path


def _run_generator(script: str, env_extra: dict[str, str], *, expect_ok: bool = True) -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(GENERATORS_DIR / script)],
        capture_output=True,
        text=True,
        env={**os.environ, **env_extra},
        timeout=30,
        check=False,
    )
    if not expect_ok:
        assert result.returncode != 0
        return []
    assert result.returncode == 0, f"{script} failed: {result.stderr}"
    return json.loads(result.stdout.strip())


def _endpoints_env(tmp_path: Path, routes: list[dict], contracts: list[dict] | None = None) -> dict[str, str]:
    env = {"YDK_COMPONENTS_ROUTE": str(_write_component_yaml(tmp_path, "route", routes))}
    if contracts is not None:
        env["YDK_COMPONENTS_CONTRACT"] = str(_write_component_yaml(tmp_path, "contract", contracts))
    return env


def _endpoints_file(tmp_path: Path, routes: list[dict], contracts: list[dict] | None = None) -> str:
    files = _run_generator("api_endpoints.py", _endpoints_env(tmp_path, routes, contracts))
    assert len(files) == 1
    return files[0]["content"]


@pytest.fixture
def endpoints_content(tmp_path: Path) -> str:
    return _endpoints_file(tmp_path, SAMPLE_ROUTES, [SAMPLE_CONTRACT])


class TestApiEndpointsOutput:
    def test_emits_one_file_per_tag(self, tmp_path: Path) -> None:
        other = {**SAMPLE_ROUTES[0], "id": "ydk:route:customers/list", "path": "/customers", "maps_to_use_case": ""}
        env = _endpoints_env(tmp_path, [*SAMPLE_ROUTES, other], [SAMPLE_CONTRACT])
        files = _run_generator("api_endpoints.py", env)
        assert [f["path"] for f in files] == ["Api/Endpoints/CustomersEndpoints.cs", "Api/Endpoints/OrdersEndpoints.cs"]

    def test_explicit_tag_wins_over_path_segment(self, tmp_path: Path) -> None:
        route = {**SAMPLE_ROUTES[0], "path": "/api/v1/things", "tag": "inventory"}
        files = _run_generator("api_endpoints.py", _endpoints_env(tmp_path, [route], [SAMPLE_CONTRACT]))
        assert files[0]["path"] == "Api/Endpoints/InventoryEndpoints.cs"

    def test_api_and_version_prefix_segments_are_skipped_for_tag(self, tmp_path: Path) -> None:
        route = {**SAMPLE_ROUTES[0], "path": "/api/v1/orders"}
        files = _run_generator("api_endpoints.py", _endpoints_env(tmp_path, [route], [SAMPLE_CONTRACT]))
        assert files[0]["path"] == "Api/Endpoints/OrdersEndpoints.cs"

    def test_no_routes_emits_no_files(self, tmp_path: Path) -> None:
        assert _run_generator("api_endpoints.py", _endpoints_env(tmp_path, [], [SAMPLE_CONTRACT])) == []

    def test_missing_route_env_fails_loudly(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "YDK_COMPONENTS_ROUTE"}
        result = subprocess.run(
            [sys.executable, str(GENERATORS_DIR / "api_endpoints.py")],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        assert result.returncode != 0
        assert "YDK_COMPONENTS_ROUTE" in result.stderr

    def test_output_is_deterministic(self, tmp_path: Path) -> None:
        env = _endpoints_env(tmp_path, SAMPLE_ROUTES, [SAMPLE_CONTRACT])
        assert _run_generator("api_endpoints.py", env) == _run_generator("api_endpoints.py", env)


class TestApiEndpointsContent:
    def test_static_class_and_extension_method(self, endpoints_content: str) -> None:
        assert "namespace Api.Endpoints;" in endpoints_content
        assert "using Application.Services;" in endpoints_content
        assert "public static class OrdersEndpoints" in endpoints_content
        assert "public static IEndpointRouteBuilder MapOrdersEndpoints(this IEndpointRouteBuilder app)" in (
            endpoints_content
        )
        assert "return app;" in endpoints_content

    def test_uses_minimal_api_map_methods(self, endpoints_content: str) -> None:
        assert 'app.MapGet("/orders", async (IOrderService orderService) =>' in endpoints_content
        assert "app.MapPost(" in endpoints_content
        assert ".WithTags(" in endpoints_content

    def test_handlers_delegate_to_injected_service(self, endpoints_content: str) -> None:
        assert "await orderService.ListOrders()" in endpoints_content
        assert "await orderService.GetOrder(orderId)" in endpoints_content
        assert "await orderService.CreateOrder(request.Total)" in endpoints_content

    def test_path_param_is_typed_from_declaration(self, endpoints_content: str) -> None:
        assert 'app.MapGet("/orders/{orderId}", async (Guid orderId, IOrderService orderService) =>' in (
            endpoints_content
        )

    def test_path_param_is_matched_fuzzily_to_contract_param(self, endpoints_content: str) -> None:
        # Route says {id}; contract param is orderId (typed uuid -> Guid).
        assert 'app.MapPost("/orders/{id}/cancel", async (Guid id, CancelOrderRequest request, ' in endpoints_content

    def test_body_request_record_built_from_declared_and_contract_params(self, endpoints_content: str) -> None:
        assert "public sealed record CreateOrderRequest(decimal Total);" in endpoints_content
        assert "async (CreateOrderRequest request, IOrderService orderService)" in endpoints_content

    def test_unclaimed_contract_param_on_body_method_joins_request_record(self, endpoints_content: str) -> None:
        assert "public sealed record CancelOrderRequest(string Reason);" in endpoints_content
        assert "await orderService.CancelOrder(id, request.Reason);" in endpoints_content

    def test_status_code_results(self, endpoints_content: str) -> None:
        # nullable return on GET-by-id -> 404 branch
        assert "result is null ? Results.NotFound() : Results.Ok(result)" in endpoints_content
        assert "return Results.Ok(result);" in endpoints_content
        assert "Results.Json(result, statusCode: 201)" in endpoints_content
        assert "return Results.NoContent();" in endpoints_content

    def test_void_method_is_awaited_without_result(self, endpoints_content: str) -> None:
        assert "await orderService.CancelOrder(id, request.Reason);" in endpoints_content
        assert "var result = await orderService.CancelOrder" not in endpoints_content

    def test_declared_body_field_absent_from_contract_stays_in_record_but_is_not_passed(self, tmp_path: Path) -> None:
        route = {
            **SAMPLE_ROUTES[2],
            "request": {"body": {"total": {"type": "decimal", "required": True}, "note": {"type": "string"}}},
        }
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "public sealed record CreateOrderRequest(string Note, decimal Total);" in content
        assert "await orderService.CreateOrder(request.Total);" in content

    def test_snake_case_route_params_become_camel_case(self, tmp_path: Path) -> None:
        route = {**SAMPLE_ROUTES[1], "path": "/orders/{order_id}/lines/{line_id}"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert '"/orders/{orderId}/lines/{lineId}"' in content

    def test_query_params_are_optional_unless_required(self, tmp_path: Path) -> None:
        route = {
            **SAMPLE_ROUTES[0],
            "maps_to_use_case": "",
            "request": {"query": {"page": {"type": "integer"}, "status": {"type": "string", "required": True}}},
        }
        content = _endpoints_file(tmp_path, [route], None)
        assert "int? page" in content
        assert "string status" in content
        assert "string? status" not in content


class TestApiEndpointsInference:
    def test_infers_service_and_method_without_maps_to(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:orders/get", "method": "GET", "path": "/orders/{order_id}"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "IOrderService orderService" in content
        assert "await orderService.GetOrder(orderId)" in content

    def test_infers_list_method_from_plural_contract_method(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:orders/list", "method": "GET", "path": "/orders"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "await orderService.ListOrders()" in content

    def test_falls_back_to_convention_when_contract_lacks_method(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:orders/delete", "method": "DELETE", "path": "/orders/{id}"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "await orderService.DeleteOrder(id)" in content
        assert "return Results.NoContent();" in content

    def test_works_without_contract_input(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:orders/get", "method": "GET", "path": "/orders/{id}"}
        content = _endpoints_file(tmp_path, [route], None)
        assert "IOrderService orderService" in content
        assert "await orderService.GetOrder(id)" in content

    def test_maps_to_without_method_infers_method_from_http_verb(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:purchases/list", "method": "GET", "path": "/purchases", "maps_to": "OrderService"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "await orderService.ListOrders()" in content

    def test_single_contract_is_used_when_tag_has_no_matching_service(self, tmp_path: Path) -> None:
        route = {"id": "ydk:route:purchases/list", "method": "GET", "path": "/purchases"}
        content = _endpoints_file(tmp_path, [route], [SAMPLE_CONTRACT])
        assert "IOrderService orderService" in content
        assert "await orderService.ListOrders()" in content


def _di_env(tmp_path: Path, entities: list[dict], contracts: list[dict]) -> dict[str, str]:
    return {
        "YDK_COMPONENTS_ENTITY": str(_write_component_yaml(tmp_path, "entity", entities)),
        "YDK_COMPONENTS_CONTRACT": str(_write_component_yaml(tmp_path, "contract", contracts)),
        "YDK_PROJECT_ROOT": str(tmp_path / "Shop"),
    }


class TestDependencyInjection:
    def test_emits_single_extensions_file(self, tmp_path: Path) -> None:
        files = _run_generator("dependency_injection.py", _di_env(tmp_path, [SAMPLE_ENTITY], [SAMPLE_CONTRACT]))
        assert [f["path"] for f in files] == ["Api/ServiceCollectionExtensions.cs"]

    def test_wires_dbcontext_repositories_and_services(self, tmp_path: Path) -> None:
        files = _run_generator("dependency_injection.py", _di_env(tmp_path, [SAMPLE_ENTITY], [SAMPLE_CONTRACT]))
        content = files[0]["content"]
        assert "namespace Api;" in content
        assert "public static class ServiceCollectionExtensions" in content
        assert "public static IServiceCollection AddApplicationServices(" in content
        assert "services.AddDbContext<AppDbContext>(options => options.UseSqlite(connectionString));" in content
        assert 'GetConnectionString("DefaultConnection")' in content
        assert "services.AddScoped<IOrderRepository, OrderRepository>();" in content
        assert "services.AddScoped<IOrderService, OrderService>();" in content

    def test_usings_match_namespaces_of_wired_types(self, tmp_path: Path) -> None:
        files = _run_generator("dependency_injection.py", _di_env(tmp_path, [SAMPLE_ENTITY], [SAMPLE_CONTRACT]))
        content = files[0]["content"]
        assert "using Application.Interfaces;" in content
        assert "using Application.Services;" in content
        assert "using Infrastructure.Persistence.Repositories;" in content
        # AppDbContext lives in the fixed "Infrastructure.Persistence" namespace
        # (efcore_dbcontext.py) -- not derived from YDK_PROJECT_ROOT, so this
        # always matches regardless of the project directory's name.
        assert "using Infrastructure.Persistence;" in content

    def test_service_name_derivation_matches_service_stubs(self, tmp_path: Path) -> None:
        contract = {"id": "ydk:contract:billing/Invoice", "methods": {}}
        entity = {"id": "ydk:entity:billing/Invoice", "fields": {"id": {"type": "uuid", "primary_key": True}}}
        files = _run_generator("dependency_injection.py", _di_env(tmp_path, [entity], [contract]))
        assert "services.AddScoped<IInvoiceService, InvoiceService>();" in files[0]["content"]

    def test_no_components_still_wires_dbcontext(self, tmp_path: Path) -> None:
        files = _run_generator("dependency_injection.py", _di_env(tmp_path, [], []))
        content = files[0]["content"]
        assert "AddDbContext<AppDbContext>" in content
        assert "AddScoped" not in content

    def test_missing_entity_env_fails_loudly(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "YDK_COMPONENTS_ENTITY"}
        result = subprocess.run(
            [sys.executable, str(GENERATORS_DIR / "dependency_injection.py")],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        assert result.returncode != 0
        assert "YDK_COMPONENTS_ENTITY" in result.stderr


class TestTemplatesExist:
    @pytest.mark.parametrize("template_path", ["api/endpoints.cs.j2", "api/service_collection_extensions.cs.j2"])
    def test_template_file_exists(self, template_path: str) -> None:
        assert (PACK_ROOT / "templates" / template_path).is_file()

    @pytest.mark.parametrize("script", ["api_endpoints.py", "dependency_injection.py"])
    def test_manifest_declares_generator_script(self, script: str) -> None:
        manifest = yaml.safe_load((PACK_ROOT / "manifest.yaml").read_text(encoding="utf-8"))
        assert any(g["script"] == f"generators/{script}" for g in manifest["generators"])
