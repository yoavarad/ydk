#!/usr/bin/env python3
"""Publish gate for go-http-service: ignite samples, build, start, probe.

Ignites samples/components into a temp project (ignition runs go mod tidy/vendor,
gofmt, go build ./..., go vet ./...), builds the binary, starts it with every required
env var set, and checks GET /healthz and /readyz -> 200, an unknown path -> JSON 404,
and a wrong method -> JSON 405 with an Allow header.
When helm is on PATH it also checks the ops-phase chart: `helm lint --strict` and
`helm template` pass with openshift.enabled true and false, and an unknown values key fails lint.
Prints a JSON report as the last stdout line; exits non-zero on any failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from ydk.core.ignition import IgnitionEngine

PACK_DIR = Path(__file__).resolve().parent.parent
_REQUIRED = re.compile(r'lookup\("([A-Z0-9_]+)", "[^"]*", true\)')


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(url: str, method: str = "GET") -> tuple[int, str, str]:
    """Return (status, body, Allow header)."""
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read().decode("utf-8"), resp.headers.get("Allow", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers.get("Allow", "")


def _json(body: str) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return body


def _helm_checks(project: Path) -> dict[str, object]:
    """Lint/template the generated chart in both platform modes; empty when helm is absent."""
    helm = shutil.which("helm")
    charts = sorted((project / "charts").glob("*/Chart.yaml"))
    if helm is None or not charts:
        return {"helm": "skipped: helm not on PATH" if helm is None else "skipped: no chart generated"}
    chart = str(charts[0].parent)

    def run(*args: str) -> int:
        out = subprocess.run([helm, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return out.returncode

    report: dict[str, object] = {}
    for mode in ("true", "false"):
        sets = ["--set", f"openshift.enabled={mode}", "--set", "ingress.enabled=true"]
        report[f"helm_lint_openshift_{mode}"] = run("lint", "--strict", chart, *sets)
        report[f"helm_template_openshift_{mode}"] = run("template", "smoke", chart, *sets)
    report["helm_lint_unknown_key_rejected"] = run("lint", "--strict", chart, "--set", "ydkSmokeUnknownKey=1") != 0
    return report


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def main() -> int:
    """Run the smoke check; return the process exit code."""
    if shutil.which("go") is None:
        return _fail("go toolchain not found on PATH")
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="go-http-service-smoke-") as tmp:
        project = Path(tmp)
        shutil.copytree(PACK_DIR, project / ".ydk" / "ignition-packs" / PACK_DIR.name)
        shutil.copytree(PACK_DIR / "samples" / "components", project / ".ydk" / "components")
        result = IgnitionEngine(project).ignite(init_answers={"http_port": str(port)})
        if result.errors:
            return _fail("ignite failed:\n" + "\n".join(result.errors))

        helm_report = _helm_checks(project)
        app = next((project / "cmd").iterdir()).name
        binary = project / "bin" / (app + (".exe" if os.name == "nt" else ""))
        build = subprocess.run(
            ["go", "build", "-o", str(binary), f"./cmd/{app}"],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if build.returncode != 0:
            return _fail("go build failed:\n" + build.stderr)

        config_go = (project / "internal" / "config" / "config.go").read_text(encoding="utf-8")
        env = {**os.environ, **{name: "smoke" for name in _REQUIRED.findall(config_go)}, "LISTEN_HOST": "127.0.0.1"}
        log_path = project / "app.log"
        with log_path.open("wb") as log:
            proc = subprocess.Popen([str(binary)], cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            healthz = 0
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    healthz, _, _ = _request(base + "/healthz")
                    break
                except OSError:
                    time.sleep(0.2)
            if healthz != 200:
                proc.kill()
                proc.wait(timeout=15)
                output = log_path.read_text(encoding="utf-8", errors="replace")
                return _fail(f"/healthz returned {healthz}; app output:\n{output}")
            readyz, _, _ = _request(base + "/readyz")
            unknown_status, unknown_body, _ = _request(base + "/ydk-smoke-unknown-path")
            wrong_status, wrong_body, allow = _request(base + "/healthz", method="DELETE")
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=15)

    report = {
        "healthz": healthz,
        "readyz": readyz,
        "unknown_status": unknown_status,
        "unknown_body": _json(unknown_body),
        "wrong_method_status": wrong_status,
        "wrong_method_body": _json(wrong_body),
        "wrong_method_allow": allow,
        **helm_report,
    }
    print(json.dumps(report))
    ok = readyz == 200 and unknown_status == 404 and isinstance(report["unknown_body"], dict)
    ok = ok and wrong_status == 405 and isinstance(report["wrong_method_body"], dict) and "GET" in allow
    ok = ok and all(v == 0 for k, v in helm_report.items() if k.startswith("helm_") and "rejected" not in k)
    ok = ok and helm_report.get("helm_lint_unknown_key_rejected", True) is True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
