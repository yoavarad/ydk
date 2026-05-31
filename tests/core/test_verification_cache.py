"""Tests for content-hash-based verification result caching."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import yaml

from odk.core.verification_cache import VerificationCache
from odk.core.verifier import Verifier
from odk.models.verification import CheckResult

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHECK_TEMPLATE = """import json, sys, time
context = json.loads(sys.stdin.read())
result = {{"name": "{name}", "passed": True, "output": "ok", "duration_seconds": 0.1, "detail": None}}
json.dump(result, sys.stdout)
sys.exit(0)
"""


def _write_plugin(
    plugin_dir: Path,
    name: str,
    *,
    trigger: str = "git:pre-commit",
    parallel: bool = True,
    timeout: int = 30,
    check_code: str | None = None,
) -> Path:
    """Create a minimal plugin folder with manifest.yaml + check.py."""
    folder = plugin_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "description": f"Test plugin: {name}",
        "trigger": trigger,
        "parallel": parallel,
        "timeout": timeout,
        "requires": [],
    }
    (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))

    if check_code is None:
        check_code = _CHECK_TEMPLATE.format(name=name)
    (folder / "check.py").write_text(check_code)
    return folder


def _make_verifier(
    tmp_path: Path,
    plugins: dict[str, dict[str, Any]] | None = None,
    *,
    use_cache: bool = True,
) -> Verifier:
    """Build a Verifier with test plugin directories and cache enabled."""
    global_dir = tmp_path / "global_verifications"
    project_dir = tmp_path / "project_verifications"
    global_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    for name, kwargs in (plugins or {}).items():
        _write_plugin(global_dir, name, **kwargs)

    return Verifier(
        project_root=tmp_path,
        global_verifications=global_dir,
        project_verifications=project_dir,
        use_cache=use_cache,
    )


def _write_py_file(tmp_path: Path, name: str, content: str) -> Path:
    """Write a .py file in the project root for hashing."""
    f = tmp_path / name
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# VerificationCache unit tests
# ---------------------------------------------------------------------------


class TestVerificationCacheUnit:
    def test_store_and_get_cached(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        result = CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)
        hashes = {"a.py": "abc123"}

        cache.store("lint", hashes, result)
        cached = cache.get_cached("lint", hashes)

        assert cached is not None
        assert cached.name == "lint"
        assert cached.passed is True
        assert cached.output == "ok"

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        assert cache.get_cached("lint", {"a.py": "abc123"}) is None

    def test_different_hashes_miss(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        result = CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)
        cache.store("lint", {"a.py": "hash1"}, result)

        # Different hash should miss
        assert cache.get_cached("lint", {"a.py": "hash2"}) is None

    def test_invalidate_specific_plugin(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        r1 = CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)
        r2 = CheckResult(name="types", passed=True, output="ok", duration_seconds=0.2)
        h = {"a.py": "abc123"}

        cache.store("lint", h, r1)
        cache.store("types", h, r2)

        cache.invalidate("lint")

        assert cache.get_cached("lint", h) is None
        assert cache.get_cached("types", h) is not None

    def test_invalidate_all(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        r = CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)
        h = {"a.py": "abc123"}

        cache.store("lint", h, r)
        cache.store("types", h, r)

        cache.invalidate()

        assert cache.get_cached("lint", h) is None
        assert cache.get_cached("types", h) is None

    def test_compute_hash_returns_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')")
        hashes = VerificationCache.compute_hash([f])

        assert str(f) in hashes
        assert len(hashes[str(f)]) == 64  # SHA256 hex length

    def test_compute_hash_skips_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "gone.py"
        hashes = VerificationCache.compute_hash([missing])
        assert hashes == {}

    def test_cache_persists_on_disk(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache1 = VerificationCache(cache_dir)
        r = CheckResult(name="lint", passed=True, output="ok", duration_seconds=0.1)
        h = {"a.py": "abc123"}
        cache1.store("lint", h, r)

        # New instance, same dir
        cache2 = VerificationCache(cache_dir)
        cached = cache2.get_cached("lint", h)
        assert cached is not None
        assert cached.passed is True

    def test_corrupt_cache_treated_as_miss(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "cache")
        h = {"a.py": "abc123"}
        # Manually write corrupt data
        path = cache._entry_path("lint", h)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json at all")

        assert cache.get_cached("lint", h) is None
        # Corrupt file should be cleaned up
        assert not path.exists()


# ---------------------------------------------------------------------------
# Integration: cache with Verifier
# ---------------------------------------------------------------------------


class TestVerifierCacheIntegration:
    def test_cache_hit_returns_stored_result(self, tmp_path: Path) -> None:
        """After first run, second run with unchanged files should hit cache."""
        _write_py_file(tmp_path, "src.py", "x = 1")
        v = _make_verifier(tmp_path, plugins={"lint": {}})
        plugins = v.discover_plugins()
        ctx: dict[str, Any] = {"project_root": str(tmp_path)}

        # First run populates cache
        r1 = asyncio.run(v.run_plugin(plugins[0], ctx))
        assert r1.passed is True

        # Second run should hit cache (no subprocess)
        r2 = asyncio.run(v.run_plugin(plugins[0], ctx))
        assert r2.passed is True
        assert r2.name == "lint"

    def test_cache_miss_on_file_change(self, tmp_path: Path) -> None:
        """Modifying a file should invalidate the cache (different hash)."""
        src = _write_py_file(tmp_path, "src.py", "x = 1")
        v = _make_verifier(tmp_path, plugins={"lint": {}})
        plugins = v.discover_plugins()
        ctx: dict[str, Any] = {"project_root": str(tmp_path)}

        # First run
        asyncio.run(v.run_plugin(plugins[0], ctx))

        # Change a file
        src.write_text("x = 2")

        # Second run - cache miss, should re-run
        r2 = asyncio.run(v.run_plugin(plugins[0], ctx))
        assert r2.passed is True

    def test_no_cache_flag_bypasses_cache(self, tmp_path: Path) -> None:
        """With use_cache=False, no cache lookup or store happens."""
        _write_py_file(tmp_path, "src.py", "x = 1")
        v = _make_verifier(tmp_path, plugins={"lint": {}}, use_cache=False)
        plugins = v.discover_plugins()
        ctx: dict[str, Any] = {"project_root": str(tmp_path)}

        asyncio.run(v.run_plugin(plugins[0], ctx))

        # Cache directory should not exist
        cache_dir = tmp_path / ".odk" / "cache" / "verification"
        assert not cache_dir.exists()

    def test_clear_cache_removes_all_entries(self, tmp_path: Path) -> None:
        """cache.invalidate() should remove all cached results."""
        _write_py_file(tmp_path, "src.py", "x = 1")
        v = _make_verifier(tmp_path, plugins={"lint": {}})
        plugins = v.discover_plugins()
        ctx: dict[str, Any] = {"project_root": str(tmp_path)}

        asyncio.run(v.run_plugin(plugins[0], ctx))

        # Cache should have an entry
        cache_dir = tmp_path / ".odk" / "cache" / "verification"
        assert cache_dir.exists()

        # Clear it
        v.cache.invalidate()
        assert not cache_dir.exists()

    def test_cache_survives_across_verifier_instances(self, tmp_path: Path) -> None:
        """Cache is file-based, so a new Verifier reads old entries."""
        _write_py_file(tmp_path, "src.py", "x = 1")
        v1 = _make_verifier(tmp_path, plugins={"lint": {}})
        plugins = v1.discover_plugins()
        ctx: dict[str, Any] = {"project_root": str(tmp_path)}

        # Populate cache with first verifier
        asyncio.run(v1.run_plugin(plugins[0], ctx))

        # New verifier instance
        v2 = _make_verifier(tmp_path, plugins={"lint": {}})
        plugins2 = v2.discover_plugins()

        # Should hit cache
        r = asyncio.run(v2.run_plugin(plugins2[0], ctx))
        assert r.passed is True
