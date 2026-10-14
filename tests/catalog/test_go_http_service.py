"""Tests for the go-http-service ignition pack.

Generator tests run the real IgnitionEngine against the pack's sample
components (a copy of a real project's .ydk/components). The Go toolchain is
made unavailable by pointing PATH at an empty directory, so post-generation
steps degrade deterministically. The integration test runs the pack's publish
smoke check and is skipped when `go` is not on PATH.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ydk.core.ignition import IgnitionEngine

PACK_DIR = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "go-http-service"
SAMPLES = PACK_DIR / "samples" / "components"
TODO_LINE = re.compile(r'^\s*panic\("not implemented"\)', re.MULTILINE)


def _ignite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, components: Path = SAMPLES) -> tuple[Path, object]:
    project = tmp_path / "project"
    shutil.copytree(PACK_DIR, project / ".ydk" / "ignition-packs" / "go-http-service")
    shutil.copytree(components, project / ".ydk" / "components")
    empty_bin = tmp_path / "nobin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    result = IgnitionEngine(project).ignite()
    return project, result


def _copy_samples(tmp_path: Path, drop: tuple[str, ...]) -> Path:
    dest = tmp_path / "components"
    shutil.copytree(SAMPLES, dest)
    for rel in drop:
        target = dest / rel
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    return dest


@pytest.fixture(scope="module")
def ignited(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object]:
    tmp_path = tmp_path_factory.mktemp("go-http-service")
    with pytest.MonkeyPatch.context() as mp:
        return _ignite(tmp_path, mp)


def _read(project: Path, rel: str) -> str:
    return (project / rel).read_text(encoding="utf-8")


class TestPackStructure:
    def test_catalog_metadata(self) -> None:
        data = yaml.safe_load((PACK_DIR / "catalog.yaml").read_text(encoding="utf-8"))
        assert data["name"] == "go-http-service"
        assert "ignition-pack" in data["tags"]
        assert "go" in data["tags"]
        assert any(c.get("command") for c in data["publish_checks"])

    def test_manifest_declares_go_stack_and_scripts_exist(self) -> None:
        data = yaml.safe_load((PACK_DIR / "manifest.yaml").read_text(encoding="utf-8"))
        assert data["stack"]["language"] == "go"
        assert any("franz-go" in dep for dep in data["runtime_dependencies"]["go"])
        for gen in data["generators"]:
            assert (PACK_DIR / gen["script"]).is_file(), gen["script"]

    def test_docs_and_samples_present(self) -> None:
        assert (PACK_DIR / "README.md").is_file()
        assert (PACK_DIR / "CHANGELOG.md").is_file()
        assert len(list(SAMPLES.rglob("*.yaml"))) >= 10


class TestIgniteSamples:
    def test_generators_succeed(self, ignited: tuple[Path, object]) -> None:
        _, result = ignited
        generator_errors = [e for e in result.errors if "Generator" in e or "generator" in e]
        assert generator_errors == []
        assert result.files_written > 0

    def test_go_mod(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        go_mod = _read(project, "go.mod")
        assert go_mod.startswith("module clopy-paste\n")
        assert "\ngo 1.22" in go_mod

    def test_main_wires_config_logger_server_and_shutdown(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        main = _read(project, "cmd/clopy-paste/main.go")
        assert "package main" in main
        assert "config.Load()" in main
        assert "slog.NewJSONHandler" in main
        assert "signal.NotifyContext" in main
        assert "syscall.SIGTERM" in main
        assert "10 * time.Second" in main
        assert "srv.Shutdown(" in main

    def test_config_reads_environment_table(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        cfg = _read(project, "internal/config/config.go")
        for var in ("INSTANCE_NAME", "KAFKA_BOOTSTRAP_SERVERS", "KAFKA_INPUT_TOPIC", "LOG_LEVEL"):
            assert f'"{var}"' in cfg
        assert "InstanceName string" in cfg
        assert 'lookup("LOG_LEVEL", "INFO", false)' in cfg  # literal default
        assert 'lookup("INSTANCE_NAME", "", true)' in cfg  # required
        assert 'lookup("CENSOR_CHARS", "", false)' in cfg  # prose default dropped
        assert "ErrInvalidConfig" in cfg

    def test_every_route_has_a_handler(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        server = _read(project, "internal/httpapi/server.go")
        for comp in (SAMPLES / "route").rglob("*.yaml"):
            route = yaml.safe_load(comp.read_text(encoding="utf-8"))
            path = "/{$}" if route["path"] == "/" else route["path"]
            assert f'"{route["method"]} {path}"' in server, route["id"]

    def test_unknown_path_and_method_wrapped_as_json(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        errors_go = _read(project, "internal/httpapi/errors.go")
        server = _read(project, "internal/httpapi/server.go")
        assert "func writeError(" in errors_go
        assert '"not found"' in errors_go
        assert "method ${method} not allowed" in errors_go
        assert "http.StatusNotFound" in server
        assert "http.StatusMethodNotAllowed" in server
        assert "recover()" in server

    def test_health_routes_implemented(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        handlers = _read(project, "internal/httpapi/handlers.go")
        healthz = handlers.split("func (s *Server) handleHealthz", 1)[1].split("\n}\n", 1)[0]
        assert "not implemented" not in healthz
        readyz = handlers.split("func (s *Server) handleReadyz", 1)[1].split("\n}\n", 1)[0]
        assert "s.ready.Load()" in readyz

    def test_business_handlers_are_todos(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        handlers = _read(project, "internal/httpapi/handlers.go")
        for name in ("handleSendMessage", "handleGetMessages"):
            body = handlers.split(f"func (s *Server) {name}", 1)[1].split("\n}\n", 1)[0]
            assert TODO_LINE.search(body), name

    def test_contracts_become_interfaces(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        contracts = _read(project, "internal/messaging/contracts.go")
        assert "type Publisher interface" in contracts
        assert "Publish(ctx context.Context, user string, text string) error" in contracts
        assert "Get(user string) []Message" in contracts
        assert "Add(user string, msg Message)\n" in contracts
        assert "Apply(s string) string" in contracts

    def test_contract_stubs_panic(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        stubs = _read(project, "internal/messaging/stubs.go")
        assert "func NewStore() Store" in stubs
        assert len(TODO_LINE.findall(stubs)) == 4  # Apply, Publish, Add, Get

    def test_entities_become_structs(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        types_go = _read(project, "internal/messaging/types.go")
        assert "type Message struct" in types_go
        assert 'Text string `json:"text"`' in types_go
        assert 'Time time.Time `json:"time"`' in types_go
        assert "Key []byte" in types_go
        assert "value.user" not in types_go

    def test_sentinel_errors(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        errs = _read(project, "internal/messaging/errors.go")
        assert 'ErrKafkaUnavailable = errors.New("kafka unavailable, message not sent")' in errs
        assert "ErrBadIncomingRecord" in errs

    def test_kafka_adapter_and_fake(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        adapter = _read(project, "internal/adapters/kafka/kafka.go")
        assert '"github.com/twmb/franz-go/pkg/kgo"' in adapter
        assert "var _ messaging.Publisher = (*Publisher)(nil)" in adapter
        assert TODO_LINE.search(adapter)
        fakes = _read(project, "internal/messaging/fakes.go")
        assert "type FakePublisher struct" in fakes
        assert "var _ Publisher = (*FakePublisher)(nil)" in fakes
        assert not (project / "internal/adapters/external-pipeline").exists()

    def test_page_embedded(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        web = _read(project, "web/web.go")
        assert "//go:embed" in web
        assert "<title>clopy-paste</title>" in _read(project, "web/main.html")
        handlers = _read(project, "internal/httpapi/handlers.go")
        index = handlers.split("func (s *Server) handleIndex", 1)[1].split("\n}\n", 1)[0]
        assert "not implemented" not in index

    def test_todos_registered_for_each_panic(self, ignited: tuple[Path, object]) -> None:
        project, result = ignited
        panics = sum(len(TODO_LINE.findall(p.read_text(encoding="utf-8"))) for p in project.rglob("*.go"))
        assert panics >= 7
        assert result.todos_registered == panics
        registry = yaml.safe_load((project / ".ydk" / "todos.yaml").read_text(encoding="utf-8"))
        assert len(registry["todos"]) == panics

    def test_post_steps_report_missing_go(self, ignited: tuple[Path, object]) -> None:
        _, result = ignited
        assert any("not runnable" in e for e in result.errors)


class TestIgniteVariants:
    def test_without_page_ext_env_or_nfr(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(
            tmp_path,
            ("page", "ext", "crosscut/ops/environment.yaml", "nfr/system/shutdown-time.yaml", "route/api/index.yaml"),
        )
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert [e for e in result.errors if "enerator" in e] == []
        assert not (project / "web").exists()
        assert not (project / "internal/adapters").exists()
        assert not (project / "internal/messaging/fakes.go").exists()
        assert "type Config struct" in _read(project, "internal/config/config.go")
        main = _read(project, "cmd/clopy-paste/main.go")
        assert "10 * time.Second" in main  # default timeout

    def test_health_routes_added_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ("route/api/healthz.yaml", "route/api/readyz.yaml"))
        project, _ = _ignite(tmp_path, monkeypatch, components)
        server = _read(project, "internal/httpapi/server.go")
        assert '"GET /healthz"' in server
        assert '"GET /readyz"' in server


class TestIgniteEdgeCases:
    def _write(self, components: Path, rel: str, data: dict) -> None:
        target = components / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    def test_reserved_namespace_routes_and_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ())
        # Contract in a namespace that clashes with a generated package.
        self._write(
            components,
            "contract/config/Reader.yaml",
            {"id": "ydk:contract:config/Reader", "description": "d", "methods": {"Read": {"params": {}}}},
        )
        # Non-GET on /healthz is a business route, not liveness; same handler name twice.
        self._write(
            components,
            "route/other/healthz.yaml",
            {"id": "ydk:route:other/healthz", "method": "POST", "path": "/healthz", "responses": {}},
        )
        # Long, non-BMP error message must survive untruncated and as a valid Go literal.
        long_msg = "quota exceeded " + "x" * 150 + " \U0001f600"
        self._write(
            components,
            "error/api/quota.yaml",
            {"id": "ydk:error:api/quota", "status_code": 429, "code": "QUOTA", "detail_template": long_msg},
        )
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert [e for e in result.errors if "enerator" in e] == []
        assert (
            (project / "internal/configdomain/contracts.go")
            .read_text(encoding="utf-8")
            .startswith("package configdomain")
        )
        assert '"clopy-paste/internal/configdomain"' in _read(project, "cmd/clopy-paste/main.go")
        handlers = _read(project, "internal/httpapi/handlers.go")
        assert handlers.count("func (s *Server) handleHealthz(") == 1
        post = handlers.split("func (s *Server) handleHealthz2", 1)[1].split("\n}\n", 1)[0]
        assert TODO_LINE.search(post)
        errors_go = _read(project, "internal/httpapi/errors.go")
        assert "x" * 150 in errors_go
        assert "\\U0001f600" in errors_go
        assert "\\ud83d" not in errors_go


@pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not on PATH")
class TestGoIntegration:
    def test_smoke_check_builds_and_serves(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PACK_DIR / "checks" / "smoke.py")],
            cwd=PACK_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["healthz"] == 200
        assert report["unknown_status"] == 404
        assert report["unknown_body"] == {"error": "not found"}
        assert report["readyz"] == 200
        assert report["wrong_method_status"] == 405
        assert report["wrong_method_body"] == {"error": "method DELETE not allowed"}
