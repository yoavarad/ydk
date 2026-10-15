#!/usr/bin/env python3
"""Generator: ops -- Dockerfile, .dockerignore and the Helm chart charts/<app>/.

Chart values come from the `Helm value` column of every ydk:crosscut env-var table:
- a dotted path (kafka.bootstrapServers) -> a string value mapped to the env var;
- `<base>.existingSecret + <key>` -> secretKeyRef from an existing Secret (no value field);
- `<base>.existingSecret or <base>.configMap + <key>` -> a read-only file mount, path as env value;
- `(fixed ...)` -> the table default, fixed in the Deployment.
Resources come from ydk:nfr cpu/memory targets, the grace period from the shutdown nfr, and a
ydk:req whose id names `single-replica` fixes replicas at 1 with strategy Recreate.
Platform features are opt-in: Route/Ingress via `ingress.enabled` (+ `openshift.enabled`), the
NetworkPolicy via `networkPolicy.enabled` (default on when a req/crosscut mentions NetworkPolicy).
Images come from the `builder_image` / `runtime_image` init answers (defaults golang:1 / scratch).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

sys.path.insert(0, str(Path(__file__).parent))

from _go_common import TEMPLATES_DIR, app_name, emit, fail, http_port, init_answers, load, split_id
from main_cmd import shutdown_timeout

CHART_VERSION = "0.1.0"
# Neutral defaults used when no ydk:nfr names cpu or memory.
DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}}
# Init answers builder_image / runtime_image override these; scratch gets CA roots from the builder.
DEFAULT_BUILDER_IMAGE = "golang:1"
DEFAULT_RUNTIME_IMAGE = "scratch"
DEFAULT_GRACE_EXTRA_SECONDS = 5
_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9]*(\.[A-Za-z][A-Za-z0-9]*)*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SECRET = re.compile(
    r"^(?P<base>[A-Za-z][\w.]*)\.existingSecret(?P<file>\s+or\s+(?P=base)\.configMap)?\s*\+\s*(?P<key>\w+)$"
)
_QUANTITY = re.compile(r"^\d+(\.\d+)?[A-Za-z]*$")
_ABS_PATH = re.compile(r"(/[\w.-]+){2,}")
_RESERVED = ("image", "openshift", "route", "ingress", "networkPolicy", "resources", "replicaCount")


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def _literal(default: str) -> str:
    """Only literal single-token defaults; prose such as 'system roots' or '<X>' templates are dropped."""
    return "" if default in ("-", "") or re.search(r"[\s<>()]", default) else default


def env_rows() -> list[dict]:
    """Rows of every crosscut table with both `Env var` and `Helm value` columns (first definition wins)."""
    rows: list[dict] = []
    seen: set[str] = set()
    for crosscut in load("crosscut"):
        table: list[str] = []
        for line in [*str(crosscut.get("specification", "")).splitlines(), ""]:
            if line.strip().startswith("|"):
                table.append(line)
                continue
            if table:
                for row in _parse_table(table):
                    if row["name"] not in seen:
                        seen.add(row["name"])
                        rows.append(row)
                table = []
    return rows


def _parse_table(lines: list[str]) -> list[dict]:
    header = [c.lower() for c in _cells(lines[0])]
    if "env var" not in header or "helm value" not in header:
        return []
    col = {
        name: header.index(name) for name in ("env var", "helm value", "required", "default", "rule") if name in header
    }
    rows = []
    for line in lines[1:]:
        cells = _cells(line)

        def cell(key: str, cells: list[str] = cells) -> str:
            return cells[col[key]] if key in col and col[key] < len(cells) else ""

        if not _ENV_NAME.match(cell("env var")):
            continue
        rows.append(
            {
                "name": cell("env var"),
                "helm": cell("helm value"),
                "required": cell("required").lower().startswith("yes"),
                "default": _literal(cell("default")),
                "rule": cell("rule"),
            }
        )
    return rows


def _set(tree: dict, path: str, value: object, source: str) -> None:
    parts = path.split(".")
    if parts[0] in _RESERVED:
        fail(f"Helm value '{path}' ({source}) clashes with a chart value the ops phase owns")
    node = tree
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            fail(f"Helm value '{path}' ({source}) nests under the scalar value '{part}'")
        node = child
    if isinstance(node.get(parts[-1]), dict):
        fail(f"Helm value '{path}' ({source}) is also a parent of other values")
    if parts[-1] in node and node[parts[-1]] != value:
        fail(f"Helm value '{path}' ({source}) is already set to {node[parts[-1]]!r} by another env var")
    node[parts[-1]] = value


def _ref(path: str) -> str:
    return ".Values." + path


def build_env(app: str) -> tuple[dict, list[dict], list[dict]]:
    """Return (values tree, env entries, file mounts) from the env-var tables."""
    values: dict = {}
    env: list[dict] = []
    mounts: list[dict] = []
    for row in env_rows():
        helm, name = row["helm"], row["name"]
        source = f"env var {name}"
        secret = _SECRET.match(helm)
        if helm.startswith("("):
            if row["default"]:
                env.append({"name": name, "value": json.dumps(row["default"])})
        elif secret and secret.group("file"):
            base, key = secret.group("base"), secret.group("key")
            found = _ABS_PATH.search(row["rule"])
            mount_dir, key_default = (
                found.group(0).rsplit("/", 1)
                if found
                else (f"/etc/{app}/{base.rsplit('.', 1)[-1]}", base.rsplit(".", 1)[-1])
            )
            _set(values, f"{base}.existingSecret", "", source)
            _set(values, f"{base}.configMap", "", source)
            _set(values, f"{base}.{key}", key_default, source)
            cond = f"or {_ref(base)}.existingSecret {_ref(base)}.configMap"
            volume = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
            shared = next((m for m in mounts if m["base"] == _ref(base)), None)
            if shared:  # several files from one Secret/ConfigMap share one volume
                mount_dir = shared["dir"]
            elif any(m["dir"] == mount_dir or m["name"] == volume for m in mounts):
                fail(f"{source}: mount path {mount_dir} or volume {volume} is already used by another file value")
            else:
                mounts.append({"name": volume, "dir": mount_dir, "base": _ref(base), "cond": cond})
            env.append({"name": name, "value": f'"{mount_dir}/{{{{ {_ref(base)}.{key} }}}}"', "cond": cond})
        elif secret:
            base, key = secret.group("base"), secret.group("key")
            _set(values, f"{base}.existingSecret", "", source)
            _set(values, f"{base}.{key}", key.removesuffix("Key") or key, source)
            env.append(
                {
                    "name": name,
                    "secret": _ref(base) + ".existingSecret",
                    "key": f"{_ref(base)}.{key}",
                    "cond": _ref(base) + ".existingSecret",
                }
            )
        elif _PATH.match(helm):
            if row["required"] or row["default"]:
                _set(values, helm, row["default"], source)
                env.append({"name": name, "value": f"{{{{ {_ref(helm)} | quote }}}}"})
            else:
                _set(values, helm, None, source)
                env.append(
                    {
                        "name": name,
                        "value": f"{{{{ {_ref(helm)} | quote }}}}",
                        "cond": f'not (kindIs "invalid" {_ref(helm)})',
                    }
                )
    env = [{"cond": "", "secret": "", "key": "", "value": "", **e} for e in env]
    return values, env, mounts


def resources() -> dict:
    """Requests/limits from ydk:nfr components whose id names cpu or memory."""
    result = json.loads(json.dumps(DEFAULT_RESOURCES))
    for nfr in load("nfr"):
        name = split_id(str(nfr.get("id", "")))[1].lower()
        kind = "cpu" if "cpu" in name else "memory" if "memory" in name else ""
        if not kind:
            continue
        target = str(nfr.get("target", ""))
        for field, word in (("requests", "requests?"), ("limits", "limits?")):
            match = re.search(rf"\b{word}\s+(\S+)", target)
            value = match.group(1).rstrip(",;.") if match else ""
            if _QUANTITY.match(value):
                result[field][kind] = value
    return result


def grace_seconds() -> int:
    for nfr in load("nfr"):
        match = re.search(r"terminationGracePeriodSeconds\s*(\d+)", str(nfr.get("target", "")))
        if "shutdown" in str(nfr.get("id", "")).lower() and match:
            return int(match.group(1))
    return shutdown_timeout()[0] + DEFAULT_GRACE_EXTRA_SECONDS


def single_replica() -> bool:
    return any("single-replica" in str(req.get("id", "")) for req in load("req"))


def network_policy_requested() -> bool:
    """Default networkPolicy.enabled: true when a ydk:req or ydk:crosscut asks for a NetworkPolicy."""
    components = [*load("req"), *load("crosscut")]
    return any("networkpolicy" in json.dumps(c, default=str).lower() for c in components)


def image_answer(key: str, default: str) -> str:
    value = str(init_answers().get(key) or "").strip()
    return value if value and not re.search(r"\s", value) else default


def schema_for(value: object) -> dict:
    """JSON schema mirroring a values tree; every object is closed (additionalProperties false)."""
    if isinstance(value, dict):
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {k: schema_for(v) for k, v in value.items()},
        }
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer", "minimum": 1}
    if value is None:
        return {"type": ["string", "null"]}
    return {"type": "string"}


def values_tree(env_values: dict, single: bool) -> dict:
    values: dict = {}
    if not single:
        values["replicaCount"] = 1
    values.update(
        {
            "image": {"repository": app_name(), "tag": "", "pullPolicy": "IfNotPresent"},
            "openshift": {"enabled": False},
            "route": {"host": ""},
            "ingress": {"enabled": False, "className": "", "host": ""},
            "networkPolicy": {"enabled": network_policy_requested(), "ingressNamespaceSelector": {}},
            "resources": resources(),
        }
    )
    values.update(env_values)
    return values


def values_schema(values: dict) -> dict:
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", **schema_for(values)}
    props = schema["properties"]
    props["image"]["properties"]["pullPolicy"]["enum"] = ["Always", "IfNotPresent", "Never"]
    # Namespace label selector: label keys are free-form, values are strings.
    props["networkPolicy"]["properties"]["ingressNamespaceSelector"] = {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    return schema


def _render(template: str, **context: object) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR / "ops")),
        undefined=StrictUndefined,
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(template).render(**context).rstrip() + "\n"


def main() -> None:
    app = app_name()
    env_values, env, mounts = build_env(app)
    single = single_replica()
    values = values_tree(env_values, single)
    chart = f"charts/{app}"
    ctx = {
        "app": app,
        "port": http_port(),
        "env": env,
        "mounts": mounts,
        "mount_cond": mounts[0]["cond"] if len(mounts) == 1 else " ".join(["or", *(f"({m['cond']})" for m in mounts)]),
        "single_replica": single,
        "grace": grace_seconds(),
        "chart_version": CHART_VERSION,
        "builder_image": image_answer("builder_image", DEFAULT_BUILDER_IMAGE),
        "runtime_image": image_answer("runtime_image", DEFAULT_RUNTIME_IMAGE),
    }
    header = f"# Default values for {app}. values.schema.json rejects unknown keys.\n"
    files = [
        {"path": "Dockerfile", "content": _render("Dockerfile.j2", **ctx)},
        {"path": ".dockerignore", "content": _render("dockerignore.j2", **ctx)},
        {"path": f"{chart}/Chart.yaml", "content": _render("chart/Chart.yaml.j2", **ctx)},
        {"path": f"{chart}/.helmignore", "content": _render("chart/helmignore.j2", **ctx)},
        {"path": f"{chart}/values.yaml", "content": header + yaml.safe_dump(values, sort_keys=False)},
        {"path": f"{chart}/values.schema.json", "content": json.dumps(values_schema(values), indent=2) + "\n"},
    ]
    for name in ("_helpers.tpl", "deployment.yaml", "service.yaml", "route.yaml", "ingress.yaml", "networkpolicy.yaml"):
        files.append({"path": f"{chart}/templates/{name}", "content": _render(f"chart/templates/{name}.j2", **ctx)})
    emit(files)


if __name__ == "__main__":
    main()
