#!/usr/bin/env python3
"""Generator: env -- Makefile, POSIX sh scripts, kind/Strimzi manifests and e2e skeleton.

Driven by the ydk:crosscut ops/local-environment prose (kind cluster, releases and, with a
ydk:ext:kafka component, Strimzi, topics and users), the env-var table's "Helm value" column,
the readiness ydk:route and ydk:test e2e cases. Every value has a generic default.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import app_name, emit, ext_technologies, fail, load, message, render, split_id

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
# Env vars whose "Helm value" key deploy.sh sets per release (only when the env table names the key).
_HELM_VARS = (
    "INSTANCE_NAME",
    "KAFKA_BOOTSTRAP_SERVERS",
    "KAFKA_INPUT_TOPIC",
    "KAFKA_OUTPUT_TOPIC",
    "KAFKA_SECURITY_PROTOCOL",
    "KAFKA_SASL_USERNAME",
    "KAFKA_CA_FILE",
)
# "Release <name>:" inside one bullet; its body runs to the next release or the end of the bullet.
_RELEASE = re.compile(r"Release ([a-z0-9-]+):(.*?)(?=Release [a-z0-9-]+:|$)")
_PROTOCOL = re.compile(r"\b(SASL_PLAINTEXT|SASL_SSL|PLAINTEXT|SSL) on (\d+)")
_RELEASE_KEYS = re.compile(r"\binstanceName |\boutput |\binput |\bingress host |" + _PROTOCOL.pattern)


def _find(pattern: str, text: str, default: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1) if match else default


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def helm_keys(crosscuts: list[dict]) -> dict[str, str]:
    """Env var -> Helm value key from every table with 'Env var' and 'Helm value' columns."""
    keys: dict[str, str] = {}
    for crosscut in crosscuts:
        header: list[str] = []
        for line in str(crosscut.get("specification", "")).splitlines():
            if not line.strip().startswith("|"):
                header = []
                continue
            cells = _cells(line)
            if not header:
                header = [c.lower() for c in cells]
                continue
            if "env var" not in header or "helm value" not in header:
                continue
            name, value = cells[header.index("env var")], cells[header.index("helm value")]
            token = value.split(" + ")[0].split(" or ")[0].strip()
            if name in _HELM_VARS and re.fullmatch(r"[A-Za-z][\w.]*", token):
                keys.setdefault(name, token)
    return keys


def _host_var(name: str) -> str:
    return "HOST_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def local_environment(crosscuts: list[dict], app: str, kafka: bool) -> dict:
    spec = next(
        (str(c.get("specification", "")) for c in crosscuts if str(c.get("id", "")).endswith("local-environment")), ""
    )
    text = " ".join(spec.split())
    ports = re.search(r"host (\d+) -> node (\d+)", text)
    env = {
        "cluster": _find(r"kind\s+\S+\s+cluster\s+'([^']+)'", text, app),
        "host_port": ports.group(1) if ports else "8080",
        "node_port": ports.group(2) if ports else "80",
        "namespace": app,
    }
    topics: dict[str, dict] = {}
    users: list[str] = []
    if kafka:
        kafka_match = re.search(r"Kafka cluster '([^']+)' in\s+namespace\s+([a-z0-9-]+)", text)
        env.update(
            strimzi_version=_find(r"Strimzi (\d+\.\d+\.\d+)", text, "1.2.0"),
            kafka_cluster=kafka_match.group(1) if kafka_match else "kafka",
            namespace=kafka_match.group(2) if kafka_match else app,
            plain_port=_find(r"plain \((\d+)", text, "9092"),
            tls_port=_find(r"tls\s*\((\d+)", text, "9093"),
        )
        for match in re.finditer(r"KafkaTopic CRs? ([\w.,\s-]+?) \((\d+) partitions?, replicas (\d+)\)", text):
            for name in re.split(r",\s*|\s+and\s+", match.group(1)):
                if name.strip():
                    topics[name.strip()] = {"partitions": int(match.group(2)), "replicas": int(match.group(3))}
        users = re.findall(r"KafkaUser ([a-z0-9.-]+) \(scram-sha-512\)", text, re.IGNORECASE)
    releases = []
    bullets = [" ".join(b.split()) for b in re.split(r"(?m)^\s*-\s+", spec)]
    for name, body in [found for bullet in bullets for found in _RELEASE.findall(bullet)]:
        if not _RELEASE_KEYS.search(body):
            continue
        protocol = _PROTOCOL.search(body) if kafka else None
        release = {
            "name": name,
            "instance": _find(r"instanceName ([a-z0-9-]+)", body, ""),
            "host": _find(r"ingress host ([\w.-]+)", body, f"{name}.local").rstrip("."),
            "var": _host_var(name),
            "output": _find(r"output ([\w.-]+)", body, "") if kafka else "",
            "input": _find(r"input ([\w.-]+)", body, "") if kafka else "",
            "protocol": protocol.group(1) if protocol else "",
            "port": protocol.group(2) if protocol else "",
            "user": "",
        }
        if release["protocol"].startswith("SASL_"):
            release["user"] = _sasl_user(name, release["protocol"], users)
        for topic in (release["output"], release["input"]):
            if topic:
                topics.setdefault(topic, {"partitions": 1, "replicas": 1})
        releases.append(release)
    if not releases:
        releases.append(
            {"name": app, "instance": "", "host": f"{app}.local", "var": _host_var(app), "protocol": "", "user": ""}
        )
        releases[0].update(output="", input="", port="")
    env["topics"] = [
        {"name": n, "slug": re.sub(r"[^a-z0-9-]+", "-", n.lower()).strip("-"), **topics[n]} for n in sorted(topics)
    ]
    env["users"] = users
    env["releases"] = releases
    return env


def _sasl_user(release: str, protocol: str, users: list[str]) -> str:
    """KafkaUser for a SASL release: the one named like the release, else the only one."""
    if release in users:
        return release
    if len(users) == 1:
        return users[0]
    found = ", ".join(users) if users else "none"
    fail(
        f"local-environment: release {release} uses {protocol} but no KafkaUser (scram-sha-512) is named "
        f"{release} and there is not exactly one to fall back to (found: {found})"
    )
    return ""


def ready_path() -> str:
    """Readiness path from the ydk:route components (GET path ending in readyz), default /readyz."""
    gets = sorted(str(r.get("path")) for r in load("route") if str(r.get("method", "")).upper() == "GET")
    return next((p for p in gets if p.rstrip("/").endswith("readyz")), "/readyz")


def e2e_tests() -> list[dict]:
    tests: list[dict] = []
    for comp in load("test"):
        if str(comp.get("level", "")).lower() != "e2e":
            continue
        tail = str(comp.get("id", "")).split(":", 2)[-1]
        base = split_id(str(comp.get("id", "")))[1].split("/")[-1].removesuffix(".e2e")
        cases = []
        for case in comp.get("cases") or []:
            if not isinstance(case, dict) or not case.get("name"):
                continue
            name = message(case["name"])
            fn = "case_" + re.sub(r"[^A-Za-z0-9_]", "_", name)
            cases.append(
                {
                    "name": name,
                    "fn": fn,
                    "description": message(case.get("description")),
                    "given": message(case.get("given")),
                    "when": message(case.get("when")),
                    "then": message(case.get("then")),
                }
            )
        fns = [c["fn"] for c in cases]
        if len(set(fns)) != len(fns):
            fail(f"{comp.get('id')}: case names map to the same sh function name: {', '.join(fns)}")
        base = re.sub(r"[^A-Za-z0-9._-]", "-", base)
        if base in ("", "lib"):
            fail(f"{comp.get('id')}: e2e test name {base!r} is empty or clashes with test/e2e/lib.sh")
        if base in [t["base"] for t in tests]:
            fail(f"{comp.get('id')}: another e2e test also generates test/e2e/{base}.sh")
        tests.append({"tail": tail, "base": base, "cases": cases})
    return tests


def helm_sets(release: dict, keys: dict[str, str]) -> list[str]:
    """`--set` arguments for one release; env-table values only when the table names their Helm key."""
    strings = {
        "image.repository": "$IMAGE_REPO",
        "image.tag": "$VERSION",
        "ingress.className": "nginx",
        "ingress.host": release["host"],
    }
    values = {"INSTANCE_NAME": release["instance"]}
    if release["protocol"]:
        values.update(
            KAFKA_BOOTSTRAP_SERVERS=f"${{KAFKA_CLUSTER}}-kafka-bootstrap.${{NAMESPACE}}.svc:{release['port']}",
            KAFKA_INPUT_TOPIC=release["input"],
            KAFKA_OUTPUT_TOPIC=release["output"],
            KAFKA_SECURITY_PROTOCOL=release["protocol"],
        )
    if release["protocol"].startswith("SASL_"):
        values["KAFKA_SASL_USERNAME"] = f"{release['user']}-credentials"
    if release["protocol"] in ("SSL", "SASL_SSL"):
        values["KAFKA_CA_FILE"] = "${KAFKA_CLUSTER}-cluster-ca-cert"
    strings.update({keys[var]: value for var, value in values.items() if value and var in keys})
    return ["--set openshift.enabled=false", *(f'--set-string {k}="{v}"' for k, v in strings.items())]


def main() -> None:
    app = app_name()
    crosscuts = load("crosscut")
    kafka = "kafka" in ext_technologies()
    env = local_environment(crosscuts, app, kafka)
    keys = helm_keys(crosscuts)
    for release in env["releases"]:
        release["sets"] = helm_sets(release, keys)
    ctx = {"app": app, "env": env, "kafka": kafka, "targets": TARGETS, "ready_path": ready_path()}
    files = [{"path": "Makefile", "content": render("env/Makefile.j2", **ctx)}]
    files.append({"path": "scripts/env.sh", "content": render("env/scripts/env.sh.j2", **ctx)})
    for target in TARGETS:
        files.append({"path": f"scripts/{target}.sh", "content": render(f"env/scripts/{target}.sh.j2", **ctx)})
    files.append({"path": "deploy/local/kind-config.yaml", "content": render("env/kind-config.yaml.j2", **ctx)})
    if kafka:
        files.append({"path": "deploy/local/kafka.yaml", "content": render("env/kafka.yaml.j2", **ctx)})
        if env["topics"]:
            files.append(
                {"path": "deploy/local/kafka-topics.yaml", "content": render("env/kafka-topics.yaml.j2", **ctx)}
            )
        if env["users"]:
            files.append({"path": "deploy/local/kafka-users.yaml", "content": render("env/kafka-users.yaml.j2", **ctx)})
    files.append({"path": "test/e2e/lib.sh", "content": render("env/e2e/lib.sh.j2", **ctx)})
    for test in e2e_tests():
        content = render("env/e2e/test.sh.j2", test=test, **ctx)
        files.append({"path": f"test/e2e/{test['base']}.sh", "content": content})
    emit(files)


if __name__ == "__main__":
    main()
