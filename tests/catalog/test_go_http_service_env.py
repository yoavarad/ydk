"""Tests for the go-http-service `env` generator (Makefile, POSIX sh scripts, Strimzi, e2e skeleton).

Generator tests run the real IgnitionEngine against the pack's sample components with
PATH emptied, so Go post-generation steps degrade deterministically. The integration
test ignites with the real toolchain and runs the generated lint/test/build scripts;
it is skipped when `go` or `sh` is not on PATH.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ydk.core.ignition import IgnitionEngine

PACK_DIR = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "go-http-service"
SAMPLES = PACK_DIR / "samples" / "kafka-service" / "components"
APP = yaml.safe_load((SAMPLES / "config" / "ops" / "app.yaml").read_text(encoding="utf-8"))["title"]
HOST_A = f"HOST_{APP.upper().replace('-', '_')}_A"
HOST_B = f"HOST_{APP.upper().replace('-', '_')}_B"
TARGETS = (
    "lint",
    "test",
    "test-integration",
    "build",
    "scan",
    "e2e",
    "publish",
    "deploy",
    "smoke",
    "env-up",
    "env-down",
)
SH = shutil.which("sh")
DASH = shutil.which("dash")


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
    tmp_path = tmp_path_factory.mktemp("go-http-service-env")
    with pytest.MonkeyPatch.context() as mp:
        return _ignite(tmp_path, mp)


def _read(project: Path, rel: str) -> str:
    return (project / rel).read_text(encoding="utf-8")


def _docs(project: Path, rel: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(_read(project, rel)) if d]


def _shell_files(project: Path) -> list[Path]:
    return sorted([*(project / "scripts").glob("*.sh"), *(project / "test" / "e2e").glob("*.sh")])


def _generator_errors(result: object) -> list[str]:
    return [e for e in result.errors if "enerator" in e]


class TestEnvGenerator:
    def test_manifest_appends_env_generator(self) -> None:
        data = yaml.safe_load((PACK_DIR / "manifest.yaml").read_text(encoding="utf-8"))
        last = data["generators"][-1]
        assert last["id"] == "env"
        assert last["script"] == "generators/env_pipeline.py"
        assert set(last["inputs"]) == {"crosscut", "ext", "test", "config"}

    def test_no_generator_errors(self, ignited: tuple[Path, object]) -> None:
        _, result = ignited
        assert _generator_errors(result) == []

    def test_makefile_has_every_target(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        makefile = _read(project, "Makefile")
        assert makefile.splitlines()[0] == ".POSIX:"
        phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
        for target in (*TARGETS, "help"):
            assert re.search(rf"\s{re.escape(target)}(\s|$)", phony), target
        for target in TARGETS:
            assert re.search(rf"^{re.escape(target)}:\n\tsh scripts/{re.escape(target)}\.sh$", makefile, re.M), target
            assert (project / "scripts" / f"{target}.sh").is_file(), target
        first_rule = re.search(r"^([a-z][\w-]*):", makefile, re.M)
        assert first_rule is not None
        assert first_rule.group(1) == "help"

    def test_scripts_are_posix_sh(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        files = _shell_files(project)
        assert len(files) >= len(TARGETS) + 3  # + env.sh, lib.sh, round-trip.sh
        for path in files:
            text = path.read_text(encoding="utf-8")
            if path.name not in ("env.sh", "lib.sh"):
                assert text.startswith("#!/bin/sh\n"), path
                assert "set -eu" in text, path
            assert "[[" not in text, path
            assert "function " not in text, path

    @pytest.mark.skipif(SH is None, reason="sh not on PATH")
    def test_scripts_pass_sh_n(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        for path in _shell_files(project):
            proc = subprocess.run([SH, "-n", str(path)], capture_output=True, text=True)
            assert proc.returncode == 0, f"{path}: {proc.stderr}"

    @pytest.mark.skipif(DASH is None, reason="dash not on PATH")
    def test_scripts_pass_dash_n(self, ignited: tuple[Path, object], tmp_path: Path) -> None:
        # dash rejects CRLF; normalise so this checks POSIX syntax only (CRLF is covered below).
        project, _ = ignited
        for path in _shell_files(project):
            copy = tmp_path / path.name
            copy.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            proc = subprocess.run([DASH, "-n", str(copy)], capture_output=True, text=True)
            assert proc.returncode == 0, f"{path}: {proc.stderr}"

    def test_generated_files_are_lf_on_disk(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        for path in [project / "Makefile", *_shell_files(project), *(project / "deploy" / "local").glob("*.yaml")]:
            assert b"\r" not in path.read_bytes(), path

    def test_kafka_topics_and_users(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        topics = {d["spec"]["topicName"]: d for d in _docs(project, "deploy/local/kafka-topics.yaml")}
        assert sorted(topics) == ["a.out", "b.out"]
        assert topics["a.out"]["metadata"]["name"] == "a-out"
        assert topics["b.out"]["metadata"]["name"] == "b-out"
        for topic in topics.values():
            assert topic["kind"] == "KafkaTopic"
            assert topic["apiVersion"] == "kafka.strimzi.io/v1"
            assert topic["metadata"]["namespace"] == APP
            assert topic["metadata"]["labels"]["strimzi.io/cluster"] == "kafka"
            assert topic["spec"]["partitions"] == 3
            assert topic["spec"]["replicas"] == 1
        users = _docs(project, "deploy/local/kafka-users.yaml")
        assert [u["metadata"]["name"] for u in users] == [f"{APP}-a"]
        assert users[0]["kind"] == "KafkaUser"
        assert users[0]["spec"]["authentication"]["type"] == "scram-sha-512"
        assert users[0]["metadata"]["labels"]["strimzi.io/cluster"] == "kafka"

    def test_kafka_cluster_listeners(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        docs = {d["kind"]: d for d in _docs(project, "deploy/local/kafka.yaml")}
        pool = docs["KafkaNodePool"]
        assert pool["spec"]["replicas"] == 1
        assert sorted(pool["spec"]["roles"]) == ["broker", "controller"]
        assert pool["metadata"]["labels"]["strimzi.io/cluster"] == "kafka"
        kafka = docs["Kafka"]
        assert kafka["metadata"] == {"name": "kafka", "namespace": APP}
        listeners = {item["name"]: item for item in kafka["spec"]["kafka"]["listeners"]}
        assert listeners["plain"]["port"] == 9092
        assert listeners["plain"]["tls"] is False
        assert listeners["tls"]["port"] == 9093
        assert listeners["tls"]["tls"] is True
        assert listeners["tls"]["authentication"]["type"] == "scram-sha-512"
        assert kafka["spec"]["entityOperator"] == {"topicOperator": {}, "userOperator": {}}

    def test_kind_config_maps_host_port(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        cfg = yaml.safe_load(_read(project, "deploy/local/kind-config.yaml"))
        assert cfg["apiVersion"] == "kind.x-k8s.io/v1alpha4"
        node = cfg["nodes"][0]
        assert node["role"] == "control-plane"
        assert node["extraPortMappings"][0]["containerPort"] == 80
        assert node["extraPortMappings"][0]["hostPort"] == 8080
        assert "ingress-ready=true" in node["kubeadmConfigPatches"][0]

    def test_env_defaults(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        env = _read(project, "scripts/env.sh")
        for line in (
            f': "${{APP:={APP}}}"',
            f': "${{CLUSTER:={APP}}}"',
            f': "${{NAMESPACE:={APP}}}"',
            ': "${KAFKA_CLUSTER:=kafka}"',
            ': "${STRIMZI_VERSION:=1.2.0}"',
            ': "${HOST_PORT:=8080}"',
        ):
            assert line in env, line
        assert "require()" in env

    def test_deploy_has_both_releases(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        deploy = _read(project, "scripts/deploy.sh")
        assert deploy.count("helm upgrade --install") == 2
        for expected in (
            f"helm upgrade --install {APP}-a",
            f"helm upgrade --install {APP}-b",
            '--set-string instanceName="side-a"',
            '--set-string instanceName="side-b"',
            f'--set-string ingress.host="a.{APP}.local"',
            f'--set-string ingress.host="b.{APP}.local"',
            '--set-string kafka.outputTopic="a.out"',
            '--set-string kafka.inputTopic="b.out"',
            '--set-string kafka.outputTopic="b.out"',
            '--set-string kafka.inputTopic="a.out"',
            '--set-string kafka.securityProtocol="SASL_SSL"',
            '--set-string kafka.securityProtocol="PLAINTEXT"',
            f'--set-string kafka.sasl.existingSecret="{APP}-a-credentials"',
            '--set-string kafka.ca.existingSecret="${KAFKA_CLUSTER}-cluster-ca-cert"',
            '--set-string image.repository="$IMAGE_REPO"',
            '--set-string image.tag="$VERSION"',
            '--set-string ingress.className="nginx"',
            "--set openshift.enabled=false",
            "--atomic --wait",
        ):
            assert expected in deploy, expected
        for line in deploy.splitlines():
            if "--set-string " in line:
                value = line.split("--set-string ", 1)[1].split("=", 1)[1].rstrip(" \\")
                assert value.startswith('"'), line
                assert value.endswith('"'), line
        assert "-kafka-bootstrap.${NAMESPACE}.svc:9093" in deploy
        assert "-kafka-bootstrap.${NAMESPACE}.svc:9092" in deploy

    def test_env_up_installs_strimzi_and_credentials(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        env_up = _read(project, "scripts/env-up.sh")
        assert "ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml" in env_up
        assert "kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=300s" in env_up
        assert "--selector" not in env_up
        assert "kind create cluster" in env_up
        assert "oci://quay.io/strimzi-helm/strimzi-kafka-operator" in env_up
        assert "deploy/local/kafka-topics.yaml" in env_up
        assert f"{APP}-a-credentials" in env_up
        assert "--dry-run=client -o yaml | kubectl apply -f -" in env_up

    def test_e2e_skeleton_markers(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        script = _read(project, "test/e2e/round-trip.sh")
        spec = yaml.safe_load((SAMPLES / "test" / "system" / "round-trip.e2e.yaml").read_text(encoding="utf-8"))
        for case in spec["cases"]:
            assert f"# ydk:test:system/round-trip.e2e case={case['name']}" in script, case["name"]
            assert f"not implemented: {case['name']}" in script
        assert '. "$(dirname "$0")/lib.sh"' in script
        lib = _read(project, "test/e2e/lib.sh")
        for fn in ("http_get()", "http_post_json()", "http_status()", "poll_until()", "fail()"):
            assert fn in lib, fn
        assert f': "${{{HOST_A}:=a.{APP}.local}}"' in lib
        for app_specific in ("/api/messages", "post_message", "get_messages", "MESSAGES_PATH"):
            assert app_specific not in lib, app_specific

    def test_smoke_is_generic(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        smoke = _read(project, "scripts/smoke.sh")
        assert f'wait_ready "${HOST_A}"' in smoke
        assert f'wait_ready "${HOST_B}"' in smoke
        assert "test/smoke/*.sh" in smoke
        assert "post" not in smoke.lower()
        assert "/readyz" in _read(project, "test/e2e/lib.sh")

    def test_e2e_runner_and_cleanup(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        assert '( set -e; "$c" )' in _read(project, "test/e2e/round-trip.sh")
        e2e = _read(project, "scripts/e2e.sh")
        assert e2e.index("kind get clusters") < e2e.index("sh scripts/env-up.sh")
        assert e2e.index("trap ") < e2e.index("sh scripts/env-up.sh")
        assert "created" in e2e
        assert "KEEP_ENV" in e2e

    def test_main_pkg_overridable(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        assert ': "${MAIN_PKG:=./cmd/$APP}"' in _read(project, "scripts/env.sh")
        build = _read(project, "scripts/build.sh")
        assert '"$MAIN_PKG"' in build
        assert "./cmd/" not in build

    @pytest.mark.skipif(SH is None, reason="sh not on PATH")
    def test_e2e_skeleton_fails(self, ignited: tuple[Path, object]) -> None:
        project, _ = ignited
        proc = subprocess.run([SH, "test/e2e/round-trip.sh"], cwd=project, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "not implemented: a-to-b" in proc.stdout + proc.stderr


class TestEnvVariants:
    def test_without_kafka_ext(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ("ext/kafka",))
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert _generator_errors(result) == []
        assert not (project / "deploy" / "local" / "kafka.yaml").exists()
        assert not (project / "deploy" / "local" / "kafka-topics.yaml").exists()
        assert not (project / "deploy" / "local" / "kafka-users.yaml").exists()
        assert (project / "Makefile").is_file()
        for target in TARGETS:
            assert (project / "scripts" / f"{target}.sh").is_file(), target
        for script in ("env-up", "env", "deploy"):
            text = _read(project, f"scripts/{script}.sh").lower()
            assert "strimzi" not in text, script
            assert "kafka" not in text, script

    def test_without_local_environment_uses_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        components = _copy_samples(tmp_path, ("crosscut/ops/local-environment.yaml",))
        project, result = _ignite(tmp_path, monkeypatch, components)
        assert _generator_errors(result) == []
        env = _read(project, "scripts/env.sh")
        assert f': "${{CLUSTER:={APP}}}"' in env
        assert ': "${STRIMZI_VERSION:=1.2.0}"' in env
        cfg = yaml.safe_load(_read(project, "deploy/local/kind-config.yaml"))
        assert cfg["nodes"][0]["extraPortMappings"][0]["hostPort"] == 8080
        assert f"helm upgrade --install {APP} " in _read(project, "scripts/deploy.sh")
        assert not (project / "deploy" / "local" / "kafka-users.yaml").exists()


MINIMAL = {
    "config/app.yaml": {"$schema": "ydk:schema:config", "id": "ydk:config:ops/app", "title": "widget-api"},
    "route/api/healthz.yaml": {
        "$schema": "ydk:schema:route",
        "id": "ydk:route:api/healthz",
        "description": "Liveness",
        "method": "GET",
        "path": "/healthz",
        "request": {},
        "responses": {"200": {"description": "alive"}},
    },
    "route/api/readyz.yaml": {
        "$schema": "ydk:schema:route",
        "id": "ydk:route:api/readyz",
        "description": "Readiness",
        "method": "GET",
        "path": "/readyz",
        "request": {},
        "responses": {"200": {"description": "ready"}},
    },
}


def test_minimal_non_kafka_service_is_generic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    components = tmp_path / "components"
    for rel, data in MINIMAL.items():
        (components / rel).parent.mkdir(parents=True, exist_ok=True)
        (components / rel).write_text(yaml.safe_dump(data), encoding="utf-8")
    project, result = _ignite(tmp_path, monkeypatch, components)
    assert _generator_errors(result) == []
    assert list((project / "deploy" / "local").glob("kafka*.yaml")) == []
    makefile = _read(project, "Makefile")
    for target in TARGETS:
        assert f"\n{target}:\n\tsh scripts/{target}.sh\n" in makefile, target
    outputs = [project / "Makefile", *_shell_files(project), *(project / "deploy" / "local").glob("*.yaml")]
    for path in outputs:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("kafka", "strimzi", APP):
            assert word not in text, f"{path}: {word}"
        if SH is not None and path.suffix == ".sh":
            proc = subprocess.run([SH, "-n", str(path)], capture_output=True, text=True)
            assert proc.returncode == 0, f"{path}: {proc.stderr}"
    assert ': "${APP:=widget-api}"' in _read(project, "scripts/env.sh")
    deploy = _read(project, "scripts/deploy.sh")
    assert deploy.count("helm upgrade --install") == 1
    assert "helm upgrade --install widget-api " in deploy


@pytest.mark.skipif(shutil.which("go") is None or SH is None, reason="go or sh not on PATH")
def test_generated_scripts_run_on_skeleton(tmp_path: Path) -> None:
    """Integration: ignite with the real Go toolchain (as checks/smoke.py does), then lint/test/build."""
    project = tmp_path / "project"
    shutil.copytree(PACK_DIR, project / ".ydk" / "ignition-packs" / PACK_DIR.name)
    shutil.copytree(SAMPLES, project / ".ydk" / "components")
    result = IgnitionEngine(project).ignite()
    assert result.errors == [], result.errors
    env = {**os.environ, "VERSION": "0.0.0-test"}
    for script in ("lint", "test", "build"):
        proc = subprocess.run(
            [SH, f"scripts/{script}.sh"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.returncode == 0, f"{script}: {proc.stdout}\n{proc.stderr}"
    assert any((project / "bin").glob(f"{APP}*"))


GENERATORS = PACK_DIR / "generators"


@pytest.fixture
def gen(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.syspath_prepend(str(GENERATORS))
    return importlib.import_module("env_pipeline")


def _local_env(spec: str) -> list[dict]:
    return [{"id": "ydk:crosscut:ops/local-environment", "specification": spec}]


class TestParsers:
    def test_topic_split_keeps_and_inside_names(self, gen: object) -> None:
        env = gen.local_environment(
            _local_env("- KafkaTopic CRs foo-and-bar, baz and qux (2 partitions, replicas 1)."), "app", True
        )
        assert [t["name"] for t in env["topics"]] == ["baz", "foo-and-bar", "qux"]

    def test_topic_mention_without_parenthetical_does_not_swallow_prose(self, gen: object) -> None:
        env = gen.local_environment(
            _local_env("- KafkaTopic CRs are listed below: t1 (2 partitions, replicas 1)."), "app", True
        )
        assert env["topics"] == []

    def test_release_requires_known_key(self, gen: object) -> None:
        env = gen.local_environment(_local_env("- Release notes: see the wiki."), "app", False)
        assert [r["name"] for r in env["releases"]] == ["app"]

    def test_release_body_not_cut_at_inner_dash(self, gen: object) -> None:
        spec = (
            "- Release r1: output a.out - mirrored, instanceName i-1, SSL on 9093,\n"
            "  ingress host h.local\n- Other bullet"
        )
        env = gen.local_environment(_local_env(spec), "app", True)
        release = env["releases"][0]
        assert release["name"] == "r1"
        assert release["instance"] == "i-1"
        assert release["host"] == "h.local"
        assert release["protocol"] == "SSL"
        assert release["port"] == "9093"

    def test_sasl_release_without_user_fails(self, gen: object) -> None:
        spec = "- Release r1: instanceName i, output o, input i2, SASL_SSL on 9093, ingress host h."
        with pytest.raises(SystemExit):
            gen.local_environment(_local_env(spec), "app", True)

    def test_sasl_release_ambiguous_users_fails(self, gen: object) -> None:
        spec = (
            "- KafkaUser u1 (scram-sha-512). KafkaUser u2 (scram-sha-512).\n"
            "- Release r1: instanceName i, SASL_SSL on 9093, ingress host h."
        )
        with pytest.raises(SystemExit):
            gen.local_environment(_local_env(spec), "app", True)

    def test_sasl_release_single_user_used(self, gen: object) -> None:
        spec = "- KafkaUser u1 (scram-sha-512).\n- Release r1: instanceName i, SASL_PLAINTEXT on 9092, ingress host h."
        env = gen.local_environment(_local_env(spec), "app", True)
        assert env["releases"][0]["protocol"] == "SASL_PLAINTEXT"
        assert env["releases"][0]["user"] == "u1"

    def _e2e(self, gen: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tests: list[dict]) -> object:
        path = tmp_path / "tests.yaml"
        path.write_text(yaml.safe_dump(tests), encoding="utf-8")
        monkeypatch.setenv("YDK_COMPONENTS_TEST", str(path))
        return gen.e2e_tests()

    @pytest.mark.parametrize(
        "tests",
        [
            [{"id": "ydk:test:system/x.e2e", "level": "e2e", "cases": [{"name": "a-b"}, {"name": "a_b"}]}],
            [{"id": "ydk:test:system/lib.e2e", "level": "e2e", "cases": [{"name": "c"}]}],
            [{"id": "ydk:test:system/.e2e", "level": "e2e", "cases": [{"name": "c"}]}],
            [
                {"id": "ydk:test:system/x.e2e", "level": "e2e", "cases": [{"name": "c"}]},
                {"id": "ydk:test:api/x.e2e", "level": "e2e", "cases": [{"name": "c"}]},
            ],
        ],
        ids=["duplicate-case-fn", "base-lib", "base-empty", "duplicate-base"],
    )
    def test_e2e_invalid_inputs_fail(
        self, gen: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tests: list[dict]
    ) -> None:
        with pytest.raises(SystemExit):
            self._e2e(gen, tmp_path, monkeypatch, tests)
