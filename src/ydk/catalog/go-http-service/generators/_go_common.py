"""Shared helpers for go-http-service generators (component loading, naming, Go types)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
TODO_STMT = 'panic("not implemented")'
# ydk:ext:<technology>/<name> is supported when templates/adapters/<technology>.go.j2 exists;
# its optional <technology>.deps lists the Go modules (module@version, one per line) it needs.
ADAPTERS_DIR = TEMPLATES_DIR / "adapters"

_GO_KEYWORDS = frozenset(
    "break case chan const continue default defer else fallthrough for func go goto if import "
    "interface map package range return select struct switch type var".split()
)
# Package names the pack generates or main.go/server.go import; a domain ns with one of these gets a suffix.
_RESERVED_PKGS = _GO_KEYWORDS | frozenset(
    "main config httpapi web adapters kafka kgo http errors time context slog os signal syscall json strings "
    "atomic embed fmt cfg ctx logger err stop api srv".split()
)
# Receiver/local names used in generated method bodies; params with these names get a suffix.
_RESERVED_LOCALS = frozenset({"recv", "out"})
_SIMPLE_TYPES = {
    "string": "string",
    "str": "string",
    "text": "string",
    "uuid": "string",
    "enum": "string",
    "integer": "int",
    "int": "int",
    "int64": "int64",
    "decimal": "float64",
    "float": "float64",
    "float64": "float64",
    "number": "float64",
    "boolean": "bool",
    "bool": "bool",
    "datetime": "time.Time",
    "date": "time.Time",
    "timestamp": "time.Time",
    "time.time": "time.Time",
    "bytes": "[]byte",
    "[]byte": "[]byte",
    "map": "map[string]any",
    "dict": "map[string]any",
    "object": "map[string]any",
    "list": "[]any",
    "array": "[]any",
    "any": "any",
    "pointer": "any",
    "error": "error",
    "context.context": "context.Context",
}
_GO_BUILTINS = frozenset({"string", "int", "int64", "float64", "bool", "byte", "rune", "any", "error"})
_TYPE_EXPR = re.compile(r"^((?:\[\])*\*?)([A-Za-z_][A-Za-z0-9_]*)$")
_NO_RESULT = frozenset({"", "none", "void", "null"})


def load(component_type: str) -> list[dict]:
    """Load all components of a type from the YDK_COMPONENTS_<TYPE> file (empty if absent)."""
    path = os.environ.get(f"YDK_COMPONENTS_{component_type.upper()}", "")
    if not path or not Path(path).exists():
        return []
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else []
    return sorted((c for c in items if isinstance(c, dict)), key=lambda c: str(c.get("id", "")))


def init_answers() -> dict:
    try:
        data = json.loads(os.environ.get("YDK_INIT_ANSWERS", "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def app_name() -> str:
    """Binary/app name: init answer `app_name`, else ydk:config title, else 'app'."""
    name = str(init_answers().get("app_name") or "")
    if not name:
        configs = load("config")
        name = str(configs[0].get("title", "")) if configs else ""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return slug or "app"


def module_path() -> str:
    return str(init_answers().get("go_module") or app_name())


def http_port() -> str:
    port = str(init_answers().get("http_port") or "8080")
    return port if port.isdigit() else "8080"


def split_id(component_id: str) -> tuple[str, str]:
    """`ydk:<type>:<ns>/<Name>` -> (ns, Name); ns defaults to 'domain'."""
    tail = component_id.split(":", 2)[-1]
    if "/" in tail:
        ns, name = tail.split("/", 1)
        return ns, name.replace("/", "-")
    return "domain", tail


def go_pkg(ns: str) -> str:
    pkg = re.sub(r"[^a-z0-9]", "", ns.lower()) or "domain"
    if pkg[0].isdigit():
        pkg = "ns" + pkg
    return pkg + "domain" if pkg in _RESERVED_PKGS else pkg


def go_ident(name: str) -> str:
    """Exported Go identifier: send-message -> SendMessage, KafkaRecord -> KafkaRecord."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name) if p]
    ident = "".join(p[:1].upper() + p[1:] for p in parts) or "X"
    return ident if not ident[0].isdigit() else "X" + ident


def go_param(name: str) -> str:
    ident = go_ident(name)
    ident = ident[:1].lower() + ident[1:]
    return ident + "_" if ident in _GO_KEYWORDS or ident in _RESERVED_LOCALS else ident


def comment(text: object, limit: int = 120) -> str:
    """First line of text, ASCII-only, safe for a // comment."""
    lines = [ln.strip() for ln in str(text or "").strip().splitlines() if ln.strip()]
    first = lines[0] if lines else ""
    first = first.encode("ascii", "replace").decode("ascii")
    return first if len(first) <= limit else first[: limit - 3].rstrip() + "..."


def message(text: object) -> str:
    """Whole runtime message (error body/sentinel text): whitespace collapsed, never truncated."""
    return " ".join(str(text or "").split())


def go_string(text: object) -> str:
    """Go double-quoted string literal; non-ASCII as \\u/\\U escapes (no JSON surrogate pairs)."""
    out = []
    for ch in json.dumps(str(text), ensure_ascii=False):
        code = ord(ch)
        if code < 0x80:
            out.append(ch)
        elif code <= 0xFFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    return "".join(out)


def go_type(raw: object, known: set[str], qualifier: str = "") -> str:
    """Map a manifest type to a Go type; entity names in `known` get `qualifier` prefixed."""
    text = str(raw or "").strip()
    simple = _SIMPLE_TYPES.get(text.lower())
    if simple:
        return simple
    match = _TYPE_EXPR.match(text)
    if not match:
        return "any"
    prefix, base = match.groups()
    if base in _GO_BUILTINS:
        return prefix + base
    if base in known:
        return prefix + qualifier + base
    return prefix + "any"


def imports_for(types: list[str]) -> list[str]:
    found: set[str] = set()
    for t in types:
        if "time.Time" in t:
            found.add("time")
        if "context.Context" in t:
            found.add("context")
    return sorted(found)


def entity_names_by_ns() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for entity in load("entity"):
        ns, name = split_id(str(entity.get("id", "")))
        result.setdefault(go_pkg(ns), set()).add(go_ident(name))
    return result


def contract_methods(contract: dict, known: set[str], qualifier: str = "") -> list[dict]:
    """Methods of a contract as {name, params, args, call_args, result, types, description}."""
    methods = []
    raw_methods = contract.get("methods") or {}
    for mname, spec in raw_methods.items() if isinstance(raw_methods, dict) else []:
        spec = spec if isinstance(spec, dict) else {}
        params = spec.get("params") or {}
        rendered, names, types, sources = [], [], [], []
        for pname, pspec in params.items() if isinstance(params, dict) else []:
            ptype = go_type((pspec or {}).get("type") if isinstance(pspec, dict) else pspec, known, qualifier)
            names.append(go_param(pname))
            sources.append(f"param {pname!r}")
            types.append(ptype)
            rendered.append(f"{go_param(pname)} {ptype}")
        scope = f"parameters of {contract.get('id')}.{mname}"
        check_unique(scope, list(zip(names, sources, strict=True)))
        returns = spec.get("returns") or {}
        rtype_raw = returns.get("type") if isinstance(returns, dict) else returns
        result = "" if str(rtype_raw or "").strip().lower() in _NO_RESULT else go_type(rtype_raw, known, qualifier)
        methods.append(
            {
                "name": go_ident(str(mname)),
                "raw_name": str(mname),
                "params": ", ".join(rendered),
                "call_args": ", ".join(names),
                "param_types": ", ".join(types),
                "result": result,
                "types": [*types, result],
                "description": comment(spec.get("description")),
            }
        )
    return methods


def ext_tech(ext: dict) -> str:
    """Technology of a ydk:ext component: ydk:ext:kafka/cluster -> kafka, ydk:ext:stripe -> stripe."""
    return str(ext.get("id", "")).split(":", 2)[-1].split("/", 1)[0].lower()


def ext_technologies() -> list[str]:
    """Every technology used by ydk:ext components, supported or not (unknown ones still get fakes)."""
    return sorted({ext_tech(e) for e in load("ext")} - {""})


def supported_ext_technologies() -> list[str]:
    """Technologies with an adapter template (templates/adapters/<tech>.go.j2)."""
    return sorted(p.name.removesuffix(".go.j2") for p in ADAPTERS_DIR.glob("*.go.j2"))


def tech_deps(tech: str) -> list[str]:
    """Go modules (module@version) from the optional templates/adapters/<tech>.deps file."""
    path = ADAPTERS_DIR / f"{tech}.deps"
    if not path.is_file():
        return []
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines())
    deps = [ln for ln in lines if ln]
    for dep in deps:
        if "@" not in dep:
            fail(f"templates/adapters/{tech}.deps: {dep!r} is not module@version")
    return deps


def is_ext_backed(contract: dict, technology: str) -> bool:
    """A contract is backed by an ext technology when its description names it."""
    return re.search(rf"\b{re.escape(technology)}\b", str(contract.get("description", "")), re.IGNORECASE) is not None


def render(template: str, **context: object) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(template).render(**context).rstrip() + "\n"


def warn(msg: str) -> None:
    """Non-fatal: ignition logs generator stderr as a warning."""
    sys.stderr.write(f"warning: {msg}\n")


def fail(msg: str) -> None:
    """Abort the generator; ignition reports stderr as the generator error."""
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def check_unique(scope: str, entries: list[tuple[str, str]]) -> None:
    """Fail when two different sources would generate the same Go identifier in one scope."""
    seen: dict[str, str] = {}
    for ident, source in entries:
        if ident in seen and seen[ident] != source:
            fail(f"name collision in {scope}: {ident} is generated by both {seen[ident]} and {source}")
        seen.setdefault(ident, source)


def emit(files: list[dict]) -> None:
    sys.stdout.write(json.dumps(files))
