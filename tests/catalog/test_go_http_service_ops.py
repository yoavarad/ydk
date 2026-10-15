"""Tests for the go-http-service `ops` phase (Dockerfile, .dockerignore, Helm chart).

Generator tests ignite the pack's sample components with the real IgnitionEngine
and PATH pointed at an empty directory (no go/helm). Helm tests render the
generated chart with the real helm CLI and are skipped when helm is not on PATH.
Docker is not exercised: the Dockerfile is checked structurally.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ydk.core.ignition import IgnitionEngine

PACK_DIR = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "go-http-service"
SAMPLES = PACK_DIR / "samples" / "components"
APP = "clopy-paste"
CHART = f"charts/{APP}"
HELM = shutil.which("helm")


def _ignite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, components: Path = SAMPLES, answers: dict | None = None
) -> tuple[Path, object]:
    project = tmp_path / "project"
    shutil.copytree(PACK_DIR, project / ".ydk" / "ignition-packs" / "go-http-service")
    shutil.copytree(components, project / ".ydk" / "components")
    empty_bin = tmp_path / "nobin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    return project, IgnitionEngine(project).ignite(init_answers=answers)


def _copy_samples(tmp_path: Path, drop: tuple[str, ...]) -> Path:
    dest = tmp_path / "components"
    shutil.copytree(SAMPLES, dest)
    for rel in drop:
        (dest / rel).unlink()
    return dest


@pytest.fixture(scope="module")
def ignited(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object]:
    tmp_path = tmp_path_factory.mktemp("go-http-service-ops")
    with pytest.MonkeyPatch.context() as mp:
        return _ignite(tmp_path, mp)


@pytest.fixture(scope="module")
def project(ignited: tuple[Path, object]) -> Path:
    return ignited[0]


def _read(project: Path, rel: str) -> str:
    return (project / rel).read_text(encoding="utf-8")


def _objects(schema: dict) -> list[dict]:
    """Every object schema with named properties (label maps have none) in a JSON schema tree."""
    found = [schema] if "properties" in schema else []
    for child in (schema.get("properties") or {}).values():
        found.extend(_objects(child))
    return found


class TestManifest:
    def test_ops_phase_declared_and_scripts_exist(self) -> None:
        data = yaml.safe_load((PACK_DIR / "manifest.yaml").read_text(encoding="utf-8"))
        ops = next(p for p in data["phases"] if p["id"] == "ops")
        for gen in ops["generators"]:
            assert (PACK_DIR / gen["script"]).is_file(), gen["script"]


class TestDockerfile:
    def test_generators_succeed(self, ignited: tuple[Path, object]) -> None:
        _, result = ignited
        assert [e for e in result.errors if "enerator" in e or "Phase" in e] == []

    def test_multi_stage_offline_static_build(self, project: Path) -> None:
        text = _read(project, "Dockerfile")
        assert text.count("FROM ") == 2
        assert "golang:" in text
        assert "ARG BUILDER_IMAGE=golang:1\n" in text
        assert "ARG RUNTIME_IMAGE=scratch\n" in text  # neutral default; no registry
        assert "/etc/ssl/certs/ca-certificates.crt" in text  # scratch gets CA roots from the builder
        assert "CGO_ENABLED=0" in text
        assert "-mod=vendor" in text
        assert "GOPROXY=off" in text
        assert "--network=none" in text
        assert "go mod download" not in text
        assert f"./cmd/{APP}" in text
        assert "-X main.version=${VERSION}" in text

    def test_runtime_is_non_root_group_zero(self, project: Path) -> None:
        text = _read(project, "Dockerfile")
        runtime = text[text.rindex("FROM ") :]
        assert "USER 1001" in runtime
        assert "--chown=1001:0" in runtime
        assert "EXPOSE 8080" in runtime
        assert f'ENTRYPOINT ["/usr/local/bin/{APP}"]' in runtime

    def test_dockerignore_allowlists_sources_and_vendor(self, project: Path) -> None:
        lines = _read(project, ".dockerignore").splitlines()
        assert lines[0] == "*"
        for keep in ("!go.mod", "!go.sum", "!vendor/", "!cmd/", "!internal/"):
            assert keep in lines

    def test_runtime_and_builder_images_from_init_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = {"runtime_image": "registry.example/ubi9/ubi-micro:9.6", "builder_image": "registry.example/go:1.27"}
        project, _ = _ignite(tmp_path, monkeypatch, answers=answers)
        text = _read(project, "Dockerfile")
        assert "ARG RUNTIME_IMAGE=registry.example/ubi9/ubi-micro:9.6\n" in text
        assert "ARG BUILDER_IMAGE=registry.example/go:1.27\n" in text
        assert "ca-certificates.crt" not in text  # a real base image brings its own CA roots

    def test_main_reads_listen_host(self, project: Path) -> None:
        main = _read(project, f"cmd/{APP}/main.go")
        assert 'os.Getenv("LISTEN_HOST")' in main
        assert "net.JoinHostPort(" in main

    def test_smoke_binds_loopback(self) -> None:
        smoke = (PACK_DIR / "checks" / "smoke.py").read_text(encoding="utf-8")
        assert '"LISTEN_HOST": "127.0.0.1"' in smoke

    def test_main_has_ldflags_version(self, project: Path) -> None:
        main = _read(project, f"cmd/{APP}/main.go")
        assert 'var version = "dev"' in main
        assert '"version", version' in main


class TestChartFiles:
    def test_chart_yaml_v2(self, project: Path) -> None:
        chart = yaml.safe_load(_read(project, f"{CHART}/Chart.yaml"))
        assert chart["apiVersion"] == "v2"
        assert chart["name"] == APP
        assert chart["version"] == chart["appVersion"]

    def test_templates_present(self, project: Path) -> None:
        for name in (
            "_helpers.tpl",
            "deployment.yaml",
            "service.yaml",
            "route.yaml",
            "ingress.yaml",
            "networkpolicy.yaml",
        ):
            assert (project / CHART / "templates" / name).is_file(), name

    def test_values_from_environment_table(self, project: Path) -> None:
        values = yaml.safe_load(_read(project, f"{CHART}/values.yaml"))
        assert values["instanceName"] == ""
        assert values["kafka"]["bootstrapServers"] == ""
        assert values["kafka"]["securityProtocol"] == "SASL_SSL"
        assert values["logLevel"] == "INFO"
        assert values["kafka"]["sasl"] == {"existingSecret": "", "usernameKey": "username", "passwordKey": "password"}
        assert values["openshift"]["enabled"] is False
        assert values["ingress"]["enabled"] is False
        assert values["networkPolicy"]["enabled"] is True  # a sample manifest asks for a NetworkPolicy
        assert "GOMEMLIMIT" not in json.dumps(values)

    def test_resources_from_nfr(self, project: Path) -> None:
        values = yaml.safe_load(_read(project, f"{CHART}/values.yaml"))
        assert values["resources"] == {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "500m", "memory": "128Mi"},
        }

    def test_no_password_value(self, project: Path) -> None:
        values = _read(project, f"{CHART}/values.yaml") + _read(project, f"{CHART}/values.schema.json")
        assert '"password"' not in values.replace('"passwordKey"', "")
        assert "password:" not in values

    def test_schema_closed_at_every_level(self, project: Path) -> None:
        schema = json.loads(_read(project, f"{CHART}/values.schema.json"))
        objects = _objects(schema)
        assert len(objects) > 5
        assert all(o.get("additionalProperties") is False for o in objects)

    def test_schema_accepts_defaults_and_rejects_unknown_key(self, project: Path) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(_read(project, f"{CHART}/values.schema.json"))
        values = yaml.safe_load(_read(project, f"{CHART}/values.yaml"))
        jsonschema.validate(values, schema)
        for bad in ({**values, "bogus": 1}, {**values, "kafka": {**values["kafka"], "password": "x"}}):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)

    def test_single_replica_recreate(self, project: Path) -> None:
        deployment = _read(project, f"{CHART}/templates/deployment.yaml")
        assert "replicas: 1" in deployment
        assert "type: Recreate" in deployment

    def test_grace_period_from_shutdown_nfr(self, project: Path) -> None:
        assert "terminationGracePeriodSeconds: 15" in _read(project, f"{CHART}/templates/deployment.yaml")


class TestVariants:
    def test_without_env_table_nfr_or_single_replica(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(
            tmp_path,
            (
                "crosscut/ops/environment.yaml",
                "nfr/system/cpu.yaml",
                "nfr/system/memory.yaml",
                "nfr/system/shutdown-time.yaml",
                "req/ops/single-replica.yaml",
            ),
        )
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert [e for e in result.errors if "enerator" in e or "Phase" in e] == []
        values = yaml.safe_load(_read(project, f"{CHART}/values.yaml"))
        assert values["replicaCount"] == 1
        assert values["resources"] == {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "256Mi"},
        }
        deployment = _read(project, f"{CHART}/templates/deployment.yaml")
        assert "replicas: {{ .Values.replicaCount }}" in deployment
        assert "RollingUpdate" in deployment
        assert "terminationGracePeriodSeconds: 15" in deployment  # default 10 s shutdown + 5


def _write_crosscut(components: Path, rows: list[str]) -> None:
    table = "\n".join(["| Env var | Helm value | Required | Default | Rule |", "|---|---|---|---|---|", *rows])
    data = {"$schema": "ydk:schema:crosscut", "id": "ydk:crosscut:ops/zz-extra", "specification": table + "\n"}
    (components / "crosscut" / "ops" / "zz-extra.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


class TestEdgeCases:
    def test_file_rows_on_one_base_share_one_mount(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ())
        _write_crosscut(
            components, ["| KAFKA_CA_KEY_FILE | kafka.ca.existingSecret or kafka.ca.configMap + keyFile | no | - | x |"]
        )
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert [e for e in result.errors if "enerator" in e or "Phase" in e] == []
        deployment = _read(project, f"{CHART}/templates/deployment.yaml")
        assert deployment.count("- name: kafka-ca\n") == 3  # one volumeMount + secret/configMap volume branches
        assert "KAFKA_CA_KEY_FILE" in deployment

    def test_plural_requests_and_limits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ())
        cpu = yaml.safe_load((components / "nfr/system/cpu.yaml").read_text(encoding="utf-8"))
        cpu["target"] = "CPU requests 100m, limits 1; plenty"
        (components / "nfr/system/cpu.yaml").write_text(yaml.safe_dump(cpu), encoding="utf-8")
        project, _ = _ignite(tmp_path, monkeypatch, components)
        values = yaml.safe_load(_read(project, f"{CHART}/values.yaml"))
        assert values["resources"]["requests"]["cpu"] == "100m"
        assert values["resources"]["limits"]["cpu"] == "1"

    def test_conflicting_rows_on_one_value_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ())
        _write_crosscut(components, ["| OTHER_LEVEL | logLevel | no | - | x |"])
        _, result = _ignite(tmp_path, monkeypatch, components)
        assert any("logLevel" in e and "OTHER_LEVEL" in e for e in result.errors)

    def test_reserved_value_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ())
        _write_crosscut(components, ["| IMAGE_TAG | image.tag | no | x | x |"])
        _, result = _ignite(tmp_path, monkeypatch, components)
        assert any("image.tag" in e for e in result.errors)


def _helm(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert HELM is not None
    return subprocess.run(
        [HELM, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def _render(project: Path, *sets: str) -> list[dict]:
    args = ["template", "rel", CHART]
    for s in sets:
        args += ["--set", s]
    out = _helm(*args, cwd=project)
    assert out.returncode == 0, out.stderr
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def _kinds(docs: list[dict]) -> dict[str, dict]:
    return {d["kind"]: d for d in docs}


@pytest.mark.skipif(HELM is None, reason="helm not on PATH")
class TestHelm:
    @pytest.mark.parametrize("openshift", ["true", "false"])
    def test_lint_strict(self, project: Path, openshift: str) -> None:
        sets = ["--set", f"openshift.enabled={openshift}", "--set", "ingress.enabled=true"]
        out = _helm("lint", "--strict", CHART, *sets, cwd=project)
        assert out.returncode == 0, out.stdout + out.stderr

    def test_lint_rejects_unknown_key(self, project: Path) -> None:
        out = _helm("lint", "--strict", CHART, "--set", "bogusKey=1", cwd=project)
        assert out.returncode != 0
        assert "bogusKey" in out.stdout + out.stderr

    def test_openshift_renders_route_not_ingress(self, project: Path) -> None:
        kinds = _kinds(_render(project, "openshift.enabled=true", "ingress.enabled=true", "route.host=app.example.com"))
        assert "Route" in kinds
        assert "Ingress" not in kinds
        tls = kinds["Route"]["spec"]["tls"]
        assert tls == {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"}

    def test_plain_renders_ingress_not_route(self, project: Path) -> None:
        kinds = _kinds(_render(project, "openshift.enabled=false", "ingress.enabled=true", "ingress.host=app.local"))
        assert "Ingress" in kinds
        assert "Route" not in kinds
        assert {"Deployment", "Service", "NetworkPolicy"} <= set(kinds)

    @pytest.mark.parametrize("openshift", ["true", "false"])
    def test_no_exposure_by_default(self, project: Path, openshift: str) -> None:
        kinds = _kinds(_render(project, f"openshift.enabled={openshift}"))
        assert "Route" not in kinds
        assert "Ingress" not in kinds

    def test_pod_security_restricted_v2(self, project: Path) -> None:
        deployment = _kinds(_render(project))["Deployment"]
        text = json.dumps(deployment)
        assert "runAsUser" not in text
        assert "fsGroup" not in text
        pod = deployment["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"] == {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}
        container = pod["containers"][0]
        sc = container["securityContext"]
        assert sc["capabilities"] == {"drop": ["ALL"]}
        assert sc["readOnlyRootFilesystem"] is True
        assert sc["allowPrivilegeEscalation"] is False
        assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
        assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
        assert deployment["spec"]["replicas"] == 1
        assert deployment["spec"]["strategy"] == {"type": "Recreate"}

    def test_env_and_secret_refs(self, project: Path) -> None:
        docs = _render(
            project,
            "instanceName=a",
            "kafka.sasl.existingSecret=kafka-user",
            "kafka.ca.existingSecret=kafka-ca",
        )
        container = _kinds(docs)["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e for e in container["env"]}
        assert env["INSTANCE_NAME"]["value"] == "a"
        assert env["GOMEMLIMIT"]["value"] == "100MiB"
        assert env["KAFKA_SASL_USERNAME"]["valueFrom"]["secretKeyRef"] == {"name": "kafka-user", "key": "username"}
        assert env["KAFKA_SASL_PASSWORD"]["valueFrom"]["secretKeyRef"] == {"name": "kafka-user", "key": "password"}
        assert env["KAFKA_CA_FILE"]["value"].startswith(f"/etc/{APP}/")
        assert "CENSOR_CHARS" not in env  # optional without a literal default: unset -> app default
        assert container["volumeMounts"][0]["readOnly"] is True

    def test_secrets_omitted_without_existing_secret(self, project: Path) -> None:
        container = _kinds(_render(project))["Deployment"]["spec"]["template"]["spec"]["containers"][0]
        names = {e["name"] for e in container["env"]}
        assert "KAFKA_SASL_PASSWORD" not in names
        assert "KAFKA_CA_FILE" not in names

    def test_ca_from_config_map(self, project: Path) -> None:
        pod = _kinds(_render(project, "kafka.ca.configMap=ca-bundle"))["Deployment"]["spec"]["template"]["spec"]
        assert pod["volumes"] == [{"name": "kafka-ca", "configMap": {"name": "ca-bundle"}}]
        mount = pod["containers"][0]["volumeMounts"]
        assert mount == [{"name": "kafka-ca", "mountPath": f"/etc/{APP}/ca", "readOnly": True}]

    def test_network_policy_selector_from_values(self, project: Path) -> None:
        default = _kinds(_render(project))["NetworkPolicy"]["spec"]["ingress"][0]["from"][0]
        assert default == {"namespaceSelector": {}}
        chosen = _kinds(_render(project, "networkPolicy.ingressNamespaceSelector.team=edge"))["NetworkPolicy"]
        assert chosen["spec"]["ingress"][0]["from"][0] == {"namespaceSelector": {"matchLabels": {"team": "edge"}}}

    def test_network_policy_can_be_disabled(self, project: Path) -> None:
        assert "NetworkPolicy" not in _kinds(_render(project, "networkPolicy.enabled=false"))

    def test_network_policy_single_ingress_rule(self, project: Path) -> None:
        policy = _kinds(_render(project))["NetworkPolicy"]["spec"]
        assert policy["policyTypes"] == ["Ingress"]
        assert len(policy["ingress"]) == 1
        rule = policy["ingress"][0]
        assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]
        assert "namespaceSelector" in rule["from"][0]


def _minimal_components(root: Path) -> Path:
    """A non-Kafka service unrelated to the samples: one config and the two health routes."""
    dest = root / "minimal"
    (dest / "route" / "api").mkdir(parents=True)
    (dest / "config" / "ops").mkdir(parents=True)
    for name in ("healthz.yaml", "readyz.yaml"):
        shutil.copy(SAMPLES / "route" / "api" / name, dest / "route" / "api" / name)
    config = {"$schema": "ydk:schema:config", "id": "ydk:config:ops/app", "title": "Hello Svc"}
    (dest / "config" / "ops" / "app.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return dest


class TestMinimalService:
    @pytest.fixture(scope="class")
    def minimal(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object]:
        tmp_path = tmp_path_factory.mktemp("go-http-service-minimal")
        with pytest.MonkeyPatch.context() as mp:
            return _ignite(tmp_path, mp, _minimal_components(tmp_path), answers={"http_port": "9090"})

    def test_generic_outputs(self, minimal: tuple[Path, object]) -> None:
        project, result = minimal
        assert [e for e in result.errors if "enerator" in e or "Phase" in e] == []
        chart = yaml.safe_load(_read(project, "charts/hello-svc/Chart.yaml"))
        assert chart["name"] == "hello-svc"
        assert "EXPOSE 9090" in _read(project, "Dockerfile")
        values = yaml.safe_load(_read(project, "charts/hello-svc/values.yaml"))
        assert set(values) == {"replicaCount", "image", "openshift", "route", "ingress", "networkPolicy", "resources"}
        assert values["networkPolicy"]["enabled"] is False
        assert values["image"]["repository"] == "hello-svc"
        ops_files = [project / "Dockerfile", project / ".dockerignore", *(project / "charts").rglob("*")]
        text = "".join(f.read_text(encoding="utf-8") for f in ops_files if f.is_file()).lower()
        for specific in ("clopy", "kafka", "ubi", "ingress-nginx", "openshift.io/ingress", "8080"):
            assert specific not in text, specific
        deployment = _read(project, "charts/hello-svc/templates/deployment.yaml")
        assert "env:" not in deployment
        assert "containerPort: 9090" in deployment

    @pytest.mark.skipif(HELM is None, reason="helm not on PATH")
    @pytest.mark.parametrize("openshift", ["true", "false"])
    def test_helm_lint_and_render(self, minimal: tuple[Path, object], openshift: str) -> None:
        project, _ = minimal
        out = _helm("lint", "--strict", "charts/hello-svc", "--set", f"openshift.enabled={openshift}", cwd=project)
        assert out.returncode == 0, out.stdout + out.stderr
        args = ["template", "rel", "charts/hello-svc", "--set", f"openshift.enabled={openshift}"]
        rendered = _helm(*args, cwd=project)
        kinds = {d["kind"] for d in yaml.safe_load_all(rendered.stdout) if d}
        assert kinds == {"Deployment", "Service"}
