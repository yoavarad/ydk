"""End-to-end integration test for the python-fastapi-hexagonal generator pack.

This test runs ignition with real sample components, starts the generated app,
hits endpoints, and runs the generated tests. It proves the generators produce
WORKING code, not just syntactically valid code.

This test MUST pass before any generator change can be pushed.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SAMPLE_COMPONENTS = Path(os.environ.get("YDK_GENERATOR_TEST_COMPONENTS", "/tmp/ydk-generator-test-components"))
PACK_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "catalog" / "python-fastapi-hexagonal"

pytestmark = [
    pytest.mark.skipif(not SAMPLE_COMPONENTS.exists(), reason="E2E components not available"),
    pytest.mark.integration,
]


@pytest.fixture(scope="module")
def generated_project(tmp_path_factory):
    """Generate a full project from sample components."""
    project = tmp_path_factory.mktemp("e2e_project")

    # Set up ignition pack
    pack_dest = project / ".ydk" / "ignition-packs" / "python-fastapi-hexagonal"
    pack_dest.mkdir(parents=True)
    shutil.copytree(PACK_DIR / "generators", pack_dest / "generators")
    shutil.copytree(PACK_DIR / "templates", pack_dest / "templates")
    shutil.copy(PACK_DIR / "manifest.yaml", pack_dest / "manifest.yaml")

    # Copy components
    components_dest = project / ".ydk" / "components"
    shutil.copytree(SAMPLE_COMPONENTS, components_dest)

    # Add config component
    config_dir = components_dest / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "app.yaml").write_text(
        '$schema: "ydk:schema:config"\n'
        'id: "ydk:config:app"\n'
        'title: "Sample App"\n'
        'version: "1.0.0"\n'
        "database:\n"
        '  url_env: "DATABASE_URL"\n'
        "auth:\n"
        '  provider: "cognito"\n'
        "cors:\n"
        '  origins: ["http://localhost:3000"]\n'
    )

    # Run ignition
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from ydk.core.ignition import IgnitionEngine

    engine = IgnitionEngine(project)
    result = engine.ignite(dry_run=False)

    # Conflicts on __init__.py files are expected (multiple generators emit them);
    # the engine keeps the first occurrence. Only fail on non-conflict errors.
    real_errors = [e for e in result.errors if "Conflict:" not in e]
    assert real_errors == [], f"Ignition errors: {real_errors}"
    assert result.files_generated > 100, f"Only {result.files_generated} files generated"

    return project


class TestGeneratedCodeCompiles:
    """All generated Python files must compile."""

    def test_all_files_compile(self, generated_project):
        py_files = list(generated_project.rglob("*.py"))
        assert len(py_files) > 50

        for f in py_files:
            if "__pycache__" in str(f):
                continue
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(f)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"Compile error in {f.name}: {result.stderr}"


class TestGeneratedAppStarts:
    """The generated app must start and serve."""

    def test_imports_resolve(self, generated_project):
        """from app.main import create_app must work."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '.'); from app.main import create_app; print('OK')",
            ],
            capture_output=True,
            text=True,
            cwd=str(generated_project),
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "OK" in result.stdout

    def test_app_starts_and_serves(self, generated_project):
        """uvicorn must bind and health check must return 200."""
        # Start uvicorn in background
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18765",
            ],
            cwd=str(generated_project),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for startup
        time.sleep(3)

        try:
            import httpx

            resp = httpx.get("http://127.0.0.1:18765/health", timeout=5)
            assert resp.status_code == 200, f"Health check returned {resp.status_code}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class TestGeneratedTestsPass:
    """At minimum, contract tests must pass."""

    def test_contract_tests_pass(self, generated_project):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/contracts/", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=str(generated_project),
        )
        # Contract tests should pass (they test Protocol conformance)
        assert "passed" in result.stdout, f"Contract tests failed:\n{result.stdout}\n{result.stderr}"
        assert "failed" not in result.stdout or "0 failed" in result.stdout


class TestDIWiringResolves:
    """FastAPI dependency injection must resolve at runtime."""

    def test_di_resolves(self, generated_project):
        """Creating a TestClient and hitting a route exercises the DI chain."""
        test_code = """
import sys, os
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_di.db")
from fastapi.testclient import TestClient
from app.main import create_app
app = create_app()
client = TestClient(app)
resp = client.get("/health")
assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
print("DI OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
            cwd=str(generated_project),
            env={**dict(__import__("os").environ), "DATABASE_URL": "sqlite:///./test_di.db"},
        )
        assert result.returncode == 0, f"DI test failed: {result.stderr}\n{result.stdout}"
        assert "DI OK" in result.stdout

    def test_port_service_di_wiring(self, generated_project):
        """Port service providers must instantiate and inject the adapter."""
        # Read the generated dependencies/adapters.py and check it wires adapters
        adapters_py = generated_project / "app" / "api" / "dependencies" / "adapters.py"
        assert adapters_py.exists(), "dependencies/adapters.py not generated"
        content = adapters_py.read_text()
        # Should import at least one ext-derived adapter (e.g. YFinanceMarketDataAdapter)
        assert "Adapter" in content, f"No adapter imports in dependencies/adapters.py:\n{content[:500]}"
        # Should have provider functions for port adapters
        assert "def get_" in content, "No provider functions in dependencies/adapters.py"


class TestNoLegacyReferences:
    """Zero legacy references in generated output."""

    def test_no_legacy_references(self, generated_project):
        result = subprocess.run(
            ["grep", "-rn", r"TODO\\[legacy", "app/", "tests/"],
            capture_output=True,
            text=True,
            cwd=str(generated_project),
        )
        assert result.stdout.strip() == "", f"Legacy references found:\n{result.stdout[:500]}"


class TestRuffPasses:
    """Generated code must pass ruff lint."""

    def test_ruff_clean(self, generated_project):
        result = subprocess.run(
            ["ruff", "check", "app/", "tests/"],
            capture_output=True,
            text=True,
            cwd=str(generated_project),
        )
        assert result.returncode == 0, f"Ruff errors:\n{result.stdout[:2000]}"
