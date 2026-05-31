"""Tests for the test generator core module."""

from __future__ import annotations

import ast

from odk.core.test_generator import ComponentTestGenerator, _class_name_from_id


class TestClassNameFromId:
    def test_entity_id(self):
        assert _class_name_from_id("odk:entity:orders/Order") == "OrdersOrder"

    def test_route_id(self):
        assert _class_name_from_id("odk:route:orders/create") == "OrdersCreate"

    def test_simple_id(self):
        assert _class_name_from_id("odk:error:NotFound") == "Notfound"


class TestGenerateFromEntity:
    def _make_manifest(self, **overrides):
        base = {"id": "odk:entity:orders/Order"}
        base.update(overrides)
        return base

    def _make_schema(self, **field_overrides):
        fields = {
            "id": {"type": "string", "required": True, "description": "ID"},
            "name": {"type": "string", "required": True, "description": "Name", "max_length": 100},
            "status": {"type": "enum", "required": True, "description": "Status", "values": ["draft", "active"]},
            "notes": {"type": "string", "required": False, "description": "Notes", "default": "none"},
        }
        fields.update(field_overrides)
        return {"fields": fields}

    def test_produces_valid_python(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), self._make_schema())
        # Should parse without SyntaxError
        ast.parse(result.test_code)

    def test_correct_test_count(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), self._make_schema())
        # required: name, status (2) + constraints: max_length, enum (2) + nullable: notes (1) + default: notes (1)
        assert result.test_count >= 4

    def test_component_id_in_result(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), self._make_schema())
        assert result.component_id == "odk:entity:orders/Order"

    def test_file_path_contains_component_name(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), self._make_schema())
        assert "order" in result.test_file_path.lower()

    def test_state_transitions_included(self):
        manifest = self._make_manifest(
            states=["draft", "active", "closed"],
            transitions=[
                {"from": "draft", "to": "active"},
                {"from": "active", "to": "closed"},
            ],
        )
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(manifest, self._make_schema())
        assert "draft" in result.test_code
        assert "active" in result.test_code
        assert "closed" in result.test_code
        ast.parse(result.test_code)

    def test_empty_schema_produces_valid_python(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), {"fields": {}})
        ast.parse(result.test_code)
        assert result.test_count >= 1

    def test_default_values_test_generated(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_entity(self._make_manifest(), self._make_schema())
        assert "default" in result.test_code.lower()


class TestGenerateFromRoute:
    def _make_manifest(self, **overrides):
        base = {
            "id": "odk:route:orders/create",
            "method": "POST",
            "path": "/orders",
            "status": 201,
            "auth": "required",
            "errors": [
                {"status": 400, "description": "validation error"},
                {"status": 409, "description": "duplicate order"},
            ],
            "request_fields": {
                "name": {"type": "string", "required": True},
                "quantity": {"type": "integer", "required": True},
            },
        }
        base.update(overrides)
        return base

    def _make_schema(self):
        return {
            "fields": {
                "id": {"type": "string", "required": True, "description": "ID"},
                "method": {"type": "enum", "required": True, "description": "HTTP method", "values": ["GET", "POST"]},
            }
        }

    def test_produces_valid_python(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_route(self._make_manifest(), self._make_schema())
        ast.parse(result.test_code)

    def test_includes_auth_test(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_route(self._make_manifest(), self._make_schema())
        assert "401" in result.test_code
        assert "Auth" in result.test_code or "auth" in result.test_code

    def test_includes_error_cases(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_route(self._make_manifest(), self._make_schema())
        assert "400" in result.test_code
        assert "409" in result.test_code

    def test_no_auth_test_when_not_required(self):
        gen = ComponentTestGenerator()
        manifest = self._make_manifest(auth="optional")
        result = gen.generate_from_route(manifest, self._make_schema())
        assert "missing_token" not in result.test_code

    def test_request_validation_tests(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_route(self._make_manifest(), self._make_schema())
        assert "name" in result.test_code
        assert "quantity" in result.test_code

    def test_happy_path_included(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_route(self._make_manifest(), self._make_schema())
        assert "201" in result.test_code


class TestGenerateFromError:
    def _make_manifest(self):
        return {"id": "odk:error:common/ValidationError"}

    def _make_schema(self):
        return {
            "fields": {
                "id": {"type": "string", "required": True, "description": "ID"},
                "code": {"type": "string", "required": True, "description": "Error code"},
                "message": {"type": "string", "required": True, "description": "Human message"},
                "details": {"type": "map", "required": False, "description": "Extra details"},
            }
        }

    def test_produces_valid_python(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_error(self._make_manifest(), self._make_schema())
        ast.parse(result.test_code)

    def test_checks_required_shape_fields(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_error(self._make_manifest(), self._make_schema())
        assert "code" in result.test_code
        assert "message" in result.test_code

    def test_test_count_covers_fields(self):
        gen = ComponentTestGenerator()
        result = gen.generate_from_error(self._make_manifest(), self._make_schema())
        # 1 required-fields test + 3 field-type tests (code, message, details)
        assert result.test_count >= 4
