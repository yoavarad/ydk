"""Tests for the test generator core module."""

from __future__ import annotations

import ast
import re

import pytest

from ydk.core.test_coverage import TestCoverageChecker
from ydk.core.test_generator import ComponentTestGenerator, _class_name_from_id


class TestClassNameFromId:
    def test_entity_id(self):
        assert _class_name_from_id("ydk:entity:orders/Order") == "OrdersOrder"

    def test_route_id(self):
        assert _class_name_from_id("ydk:route:orders/create") == "OrdersCreate"

    def test_simple_id(self):
        assert _class_name_from_id("ydk:error:NotFound") == "Notfound"


class TestGenerateFromEntity:
    def _make_manifest(self, **overrides):
        base = {"id": "ydk:entity:orders/Order"}
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
        assert result.component_id == "ydk:entity:orders/Order"

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
            "id": "ydk:route:orders/create",
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
        return {"id": "ydk:error:common/ValidationError"}

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


class TestGenerateGoFromTest:
    def _manifest(self, level="unit", **overrides):
        base = {
            "id": f"ydk:test:messaging/store.{level}",
            "level": level,
            "target": "ydk:entity:messaging/Store",
            "cases": [
                {"name": "fifo-101", "given": "empty store", "when": "push a then b", "then": "pop returns a"},
                {"name": "empty-pop", "given": "empty store", "when": "pop", "then": "error"},
            ],
        }
        base.update(overrides)
        return base

    def test_one_subtest_per_case(self):
        result = ComponentTestGenerator().generate_go_from_test(self._manifest())
        assert result.test_count == 2
        assert result.test_code.count("t.Run(") == 2
        assert 't.Run("fifo-101"' in result.test_code
        assert "func TestStore(t *testing.T) {" in result.test_code
        assert "package messaging" in result.test_code
        assert 't.Fatal("YDK-TODO: implement")' in result.test_code
        assert "//go:build" not in result.test_code

    def test_given_when_then_comments(self):
        code = ComponentTestGenerator().generate_go_from_test(self._manifest()).test_code
        assert "// Given: empty store" in code
        assert "// When: push a then b" in code
        assert "// Then: pop returns a" in code

    def test_integration_gets_build_tag(self):
        code = ComponentTestGenerator().generate_go_from_test(self._manifest("integration")).test_code
        assert code.startswith("//go:build integration\n\npackage messaging")

    def test_default_path(self):
        result = ComponentTestGenerator().generate_go_from_test(self._manifest())
        assert result.test_file_path == "messaging/store_test.go"

    def test_case_name_quotes_escaped(self):
        m = self._manifest(cases=[{"name": 'say "hi"', "given": "g", "when": "w", "then": "t"}])
        code = ComponentTestGenerator().generate_go_from_test(m).test_code
        assert 't.Run("say \\"hi\\""' in code

    def test_multiline_comment_lines_prefixed(self):
        m = self._manifest(cases=[{"name": "a", "given": "l1\nl2", "when": "w", "then": "t"}])
        code = ComponentTestGenerator().generate_go_from_test(m).test_code
        assert "// Given: l1\n\t\t// l2" in code

    def test_missing_cases_in_existing_file(self):
        existing = (
            'package messaging\n\nfunc TestStore(t *testing.T) {\n\tt.Run("fifo-101", func(t *testing.T) {})\n}\n'
        )
        gen = ComponentTestGenerator()
        assert gen.missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_lowercase_target_func_name_is_runnable_by_go_test(self):
        m = self._manifest(target="ydk:adapter:messaging/cluster")
        code = ComponentTestGenerator().generate_go_from_test(m).test_code
        assert "func TestCluster(t *testing.T) {" in code

    def test_integration_path_and_func_do_not_collide_with_unit(self):
        r = ComponentTestGenerator().generate_go_from_test(self._manifest("integration"))
        assert r.test_file_path == "messaging/store_integration_test.go"
        assert "func TestStoreIntegration(" in r.test_code

    def test_non_ascii_name_kept_literal(self):
        m = self._manifest(cases=[{"name": "ok-😀", "given": "g", "when": "w", "then": "t"}])
        assert 't.Run("ok-😀"' in ComponentTestGenerator().generate_go_from_test(m).test_code

    def test_package_name_sanitized_to_go_identifier(self):
        gen = ComponentTestGenerator()
        for ns, expected in [
            ("my-pkg.v2", "my_pkg_v2"),
            ("9lives", "p9lives"),
            ("type", "type_"),
            ("Msg", "msg"),
            ("-", "tests"),
        ]:
            m = self._manifest(id=f"ydk:test:{ns}/store.unit")
            assert f"package {expected}\n" in gen.generate_go_from_test(m).test_code

    def test_default_path_sanitized(self):
        gen = ComponentTestGenerator()
        m = self._manifest(id="ydk:test:../evil:x/st ore.unit")
        path = gen.generate_go_from_test(m).test_file_path
        assert ".." not in path.split("/")
        assert not any(ch in path for ch in ':\\ "<>|*?')
        assert path.endswith("_test.go")

    def test_missing_cases_backtick_literal(self):
        existing = "func TestStore(t *testing.T) {\n\tt.Run(`fifo-101`, func(t *testing.T) {})\n}\n"
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_missing_cases_table_driven(self):
        existing = (
            "func TestStore(t *testing.T) {\n"
            '\tcases := []struct{ name string }{\n\t\t{name: "fifo-101"},\n\t\t{"empty-pop"},\n\t}\n'
            "\tfor _, tc := range cases {\n\t\tt.Run(tc.name, func(t *testing.T) {})\n\t}\n}\n"
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == []

    def test_table_driven_partial(self):
        existing = (
            'func TestStore(t *testing.T) {\n\tcases := []struct{ name string }{{name: "fifo-101"}}\n'
            "\tfor _, tc := range cases {\n\t\tt.Run(tc.name, func(t *testing.T) {})\n\t}\n}\n"
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_name_string_without_dynamic_run_is_not_covered(self):
        existing = 'func TestStore(t *testing.T) {\n\t_ = "fifo-101"\n}\n'
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["fifo-101", "empty-pop"]

    _LOOP = "\tfor _, tc := range cases {\n\t\tt.Run(tc.name, func(t *testing.T) {})\n\t}\n}\n"

    def test_table_driven_decoy_outside_table_not_covered(self):
        existing = (
            "func TestStore(t *testing.T) {\n"
            '\tother := []string{"fifo-101", "empty-pop"}\n\t_ = struct{ a string }{a: "empty-pop"}\n'
            '\tcases := []struct{ name string }{{name: "fifo-101"}}\n' + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_table_driven_commented_cases_missing(self):
        existing = (
            "func TestStore(t *testing.T) {\n\tcases := []struct{ name string }{\n"
            '\t\t{name: "fifo-101"},\n\t\t// {name: "empty-pop"},\n\t\t/* {"empty-pop"}, */\n\t}\n' + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_table_driven_non_name_field_not_covered(self):
        existing = (
            "func TestStore(t *testing.T) {\n\tcases := []struct{ name, desc string }{\n"
            '\t\t{name: "fifo-101", desc: "empty-pop"},\n\t}\n' + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_table_driven_unkeyed_and_multiline_table(self):
        existing = (
            "func TestStore(t *testing.T) {\n\tcases := []struct{ name string }{\n"
            '\t\t{\n\t\t\t"fifo-101",\n\t\t},\n\t\t{"empty-pop"},\n\t}\n' + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == []

    def test_table_driven_nested_literal_not_covered(self):
        existing = (
            "func TestStore(t *testing.T) {\n\tcases := []struct{ name string; tags []string }{\n"
            '\t\t{name: "fifo-101", tags: []string{"empty-pop"}},\n\t}\n' + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    _TBL2 = 'cases := []struct{ name string }{{name: "fifo-101"}, {name: "empty-pop"}}\n'

    def test_table_driven_same_var_name_scoped_per_function(self):
        existing = (
            "func TestOther(t *testing.T) {\n\t"
            + self._TBL2
            + self._LOOP
            + '\nfunc TestStore(t *testing.T) {\n\tcases := []struct{ name string }{{name: "fifo-101"}}\n'
            + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["empty-pop"]

    def test_table_driven_other_function_table_not_consulted(self):
        existing = (
            "func TestOther(t *testing.T) {\n\t"
            + self._TBL2
            + self._LOOP
            + "\nfunc TestStore(t *testing.T) {\n"
            + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == ["fifo-101", "empty-pop"]

    def test_table_driven_selector_range_target(self):
        existing = (
            'func TestStore(t *testing.T) {\n\tcases := []struct{ name string }{{name: "fifo-101"}, {"empty-pop"}}\n'
            "\tfor _, tc := range s.cases {\n\t\tt.Run(tc.name, func(t *testing.T) {})\n\t}\n}\n"
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == []

    def test_table_driven_var_declarations(self):
        for decl in (
            "var cases = []struct{ name string }{",
            "var cases []struct{ name string } = []struct{ name string }{",
        ):
            existing = (
                "func TestStore(t *testing.T) {\n\t"
                + decl
                + '\n\t\t{name: "fifo-101"},\n\t\t{"empty-pop"},\n\t}\n'
                + self._LOOP
            )
            assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == [], decl

    def test_table_driven_package_level_var(self):
        existing = (
            'var cases = []struct{ name string }{\n\t{name: "fifo-101"},\n\t{"empty-pop"},\n}\n\n'
            "func TestStore(t *testing.T) {\n" + self._LOOP
        )
        assert ComponentTestGenerator().missing_go_cases(self._manifest(), existing) == []

    def test_generated_source_plausible(self):
        for level in ("unit", "integration"):
            code = ComponentTestGenerator().generate_go_from_test(self._manifest(level)).test_code
            body = code.split("package ", 1)[1]
            assert re.match(r"[a-z_][a-z0-9_]*\n\nimport \"testing\"\n\nfunc Test\w+\(t \*testing\.T\) \{\n", body)
            assert code.count("{") == code.count("}")
            assert code.count("(") == code.count(")")
            assert code.endswith("}\n")


class TestGoRoundTripWithCoverage:
    @pytest.mark.parametrize(
        "target", ["ydk:adapter:messaging/cluster", "ydk:entity:messaging/kafka-adapter", "ydk:entity:messaging/Store"]
    )
    @pytest.mark.parametrize("level", ["unit", "integration"])
    def test_generated_file_counts_as_implemented(self, tmp_path, target, level):
        manifest = {
            "id": f"ydk:test:messaging/thing.{level}",
            "level": level,
            "target": target,
            "cases": [{"name": "a", "given": "g", "when": "w", "then": "t"}],
        }
        code = ComponentTestGenerator().generate_go_from_test(manifest).test_code
        go_file = tmp_path / "thing_test.go"
        go_file.write_text(code)
        covered = TestCoverageChecker._is_implemented(
            manifest["id"], str(manifest["target"]).rsplit("/", 1)[-1].replace(".", ""), "a", [(go_file, code)]
        )
        assert covered
