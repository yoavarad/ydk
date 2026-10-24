"""Ignition engine — reads installed packs + YDK components, runs generators, produces skeleton."""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ydk.core.doctor import _GO_DIRECTIVE_RE
from ydk.core.scaffold_state import ScaffoldState
from ydk.models.ignition import GeneratedFile, IgnitionResult

if TYPE_CHECKING:
    from ydk.core.todo_manager import TodoManager

logger = logging.getLogger("ydk.ignition")

_TODO_PATTERN = "raise NotImplementedError"
# Leading component ID in a TODO comment, minus a trailing ".Method" (e.g. "ydk:contract:ns/Svc.Run: ...").
_COMPONENT_REF_RE = re.compile(
    r"^(ydk:[a-z][a-z0-9_-]*:[A-Za-z0-9_./-]*?[A-Za-z0-9_-])(?:\.[A-Z]\w*)?(?=\.?(?:[:\s]|$))"
)


def _component_refs(description: str) -> list[str]:
    """Component IDs named at the start of a TODO marker comment."""
    match = _COMPONENT_REF_RE.match(description)
    return [match.group(1)] if match else []


def _reconcile(todo_mgr: TodoManager, path: str, markers: list[dict]) -> None:
    """Attach component refs parsed from each marker's comment, then reconcile the file."""
    for marker in markers:
        marker["component_refs"] = _component_refs(marker["description"])
    todo_mgr.reconcile(path, markers)


_GENERATOR_TIMEOUT = 120
# Numeric version leading a golang image tag: reg:5000/golang:1.25.3-alpine -> 1.25.3.
_IMAGE_TAG_VERSION_RE = re.compile(r"(?:^|/)golang:(\d+(?:\.\d+)*)[^:/]*$")


def _to_posix(path: str) -> str:
    """Forward slashes, no leading './'."""
    posix = path.replace("\\", "/")
    while posix.startswith("./"):
        posix = posix[2:]
    return posix


def _matches_any(path: str, patterns: list[str]) -> bool:
    """True when *path* matches one of the fnmatch *patterns* (both normalized by _to_posix)."""
    posix = _to_posix(path)
    return any(fnmatch.fnmatchcase(posix, _to_posix(pattern)) for pattern in patterns)


class IgnitionError(Exception):
    """Raised when ignition fails fatally."""


def _go_directive(go_mod: Path) -> str | None:
    """The `go` directive of a go.mod file, or None if the file or directive is missing."""
    if not go_mod.is_file():
        return None
    match = _GO_DIRECTIVE_RE.search(go_mod.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _go_mod_requires(text: str) -> list[str]:
    """`module@version` for each direct require (single-line or block) in a go.mod.

    `// indirect` requires (added by an earlier go mod tidy) are skipped: tidy re-resolves them.
    """
    deps: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line, _, note = raw.partition("//")
        line = line.strip()
        if note.strip().startswith("indirect"):
            continue
        if in_block:
            if line == ")":
                in_block = False
                continue
        elif line.replace(" ", "") == "require(":
            in_block = True
            continue
        elif line.startswith("require "):
            line = line[len("require ") :].strip()
        else:
            continue
        parts = line.split()
        if len(parts) == 2:
            deps.append(f"{parts[0]}@{parts[1]}")
    return deps


class IgnitionEngine:
    """Reads installed ignition pack + YDK components, runs generators, produces skeleton."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._packs_dir = self._root / ".ydk" / "ignition-packs"
        self._pack_dir: Path | None = None  # resolved lazily in _load_pack
        self._components_dir = self._root / ".ydk" / "components"

    def ignite(
        self,
        init_answers: dict[str, str] | None = None,
        dry_run: bool = False,
        force: bool = False,
        only: list[str] | None = None,
    ) -> IgnitionResult:
        """Run the full ignition pipeline.

        *only* (glob patterns, matched with fnmatch against the project-relative POSIX path) runs
        every generator but keeps only matching files: the rest are not written, hashed or scanned
        for TODOs, and runtime dependency installation is skipped. Retrofit mode for existing repos.
        """
        start = time.monotonic()
        errors: list[str] = []
        warnings: list[str] = []
        answers = init_answers or {}

        # 1. Validate pack is installed
        pack = self._load_pack()
        if not pack:
            msg = f"No ignition pack found in {self._packs_dir}"
            raise IgnitionError(msg)

        # 2. Read all components, group by type
        component_data = self._assemble_components()
        if not component_data:
            msg = "No components found in .ydk/components/. Run Stage 01 brainstorming first."
            raise IgnitionError(msg)

        # 3. Run generators — phased or flat (top-level generators run before phases)
        if "phases" in pack:
            all_generated = []
            if "generators" in pack:
                top_generated, top_errors = self._ignite_flat(pack, component_data, answers)
                all_generated.extend(top_generated)
                errors.extend(top_errors)
            phase_generated, phase_errors = self._ignite_phased(pack, component_data, answers, dry_run)
            all_generated.extend(phase_generated)
            errors.extend(phase_errors)
        else:
            all_generated, flat_errors = self._ignite_flat(pack, component_data, answers)
            errors.extend(flat_errors)

        # 4. Detect path conflicts across generators — conflicts are warnings, not errors
        conflicts = self._detect_conflicts(all_generated)
        if conflicts:
            warnings.extend(conflicts)
            # Keep only the first occurrence of each path
            seen_paths: set[str] = set()
            deduped: list[GeneratedFile] = []
            for gf in all_generated:
                if gf.path in seen_paths:
                    warnings.append(f"Skipping duplicate: '{gf.path}' (keeping first)")
                    continue
                seen_paths.add(gf.path)
                deduped.append(gf)
            all_generated = deduped

        files_generated = len(all_generated)
        files_excluded = 0
        if only:
            matching = [gf for gf in all_generated if _matches_any(gf.path, only)]
            files_excluded = len(all_generated) - len(matching)
            all_generated = matching
            if not matching:
                warnings.append(f"--only matched no generated files: {', '.join(only)}")

        # 4. Track hashes for idempotency
        state = ScaffoldState(self._root / ".ydk" / "scaffold-state.yaml")
        to_write, skipped = self._filter_files(all_generated, state, force=force, warnings=warnings)
        merge_manually: list[str] = []
        if only and not force:
            written = {gf.path for gf in to_write}
            merge_manually = [
                gf.path
                for gf in all_generated
                if gf.path not in written and state.is_developer_owned(gf.path, self._root)
            ]
            # Retrofit: a file already on disk with no recorded hash (hand-made, or ignited before
            # hashes were tracked) and different content is treated as developer-owned too.
            untracked = [gf for gf in to_write if self._is_untracked_edit(gf, state)]
            for gf in untracked:
                warnings.append(f"Skipped untracked existing file: {gf.path}")
                merge_manually.append(gf.path)
            untracked_paths = {gf.path for gf in untracked}
            to_write = [gf for gf in to_write if gf.path not in untracked_paths]
            skipped += len(untracked)

        # 5. Write files (unless dry-run)
        written_paths: list[Path] = []
        if not dry_run:
            for gf in to_write:
                full = self._root / gf.path
                full.parent.mkdir(parents=True, exist_ok=True)
                content = gf.content
                full.write_text(content, encoding="utf-8", newline="\n")
                state.update(gf.path, content)
                written_paths.append(full)
            state.save()

        # 6. Register TODOs for each raise NotImplementedError
        todo_count = self._register_todos(to_write) if not dry_run else 0

        # 7-8. Post-generation checks + runtime dependencies (per pack language)
        dependencies_installed: list[str] = []
        if not dry_run:
            post_errors, dependencies_installed = self._run_post_steps(
                pack, written_paths, warnings, answers, install_deps=not only
            )
            errors.extend(post_errors)
            # Post-steps rewrite files in place (gofmt -w, ruff format, go get/tidy on go.mod); record
            # the rewritten content so a re-ignite does not mistake it for a developer edit.
            for gf in to_write:
                full = self._root / gf.path
                if full.exists():
                    on_disk = full.read_text(encoding="utf-8")
                    if on_disk != gf.content:
                        state.record_formatted(gf.path, on_disk)
            state.save()

        duration = time.monotonic() - start

        return IgnitionResult(
            files_generated=files_generated,
            files_written=len(to_write),
            files_skipped=skipped,
            todos_registered=todo_count,
            errors=errors,
            warnings=warnings,
            duration_seconds=round(duration, 2),
            dependencies_installed=dependencies_installed,
            files_excluded=files_excluded,
            merge_manually=merge_manually,
        )

    def _run_post_steps(
        self,
        pack: dict,
        written_paths: list[Path],
        warnings: list[str],
        answers: dict[str, str] | None = None,
        *,
        install_deps: bool = True,
    ) -> tuple[list[str], list[str]]:
        """Run language-specific post-generation steps. Returns (errors, installed deps).

        install_deps=False (--only) skips dependency installation (uv add / go get + tidy + vendor), which
        rewrites pyproject.toml/go.mod. The per-file checks (and go build/vet) still run.
        """
        language = str(pack.get("stack", {}).get("language", "python")).lower()
        if not install_deps:
            if language == "go":
                return self._post_generate_go(written_paths), []
            return (self._post_generate(written_paths) if written_paths else []), []
        if language == "go":
            # Deps first: go mod tidy / go build need modules resolved.
            installed = self._install_go_deps(pack, warnings)
            self._check_go_builder_image(answers or {}, warnings)
            return self._post_generate_go(written_paths), installed
        errors = self._post_generate(written_paths) if written_paths else []
        return errors, self._install_runtime_deps(pack, warnings)

    def _install_go_deps(self, pack: dict, warnings: list[str]) -> list[str]:
        """Add Go modules (pinned) via go get, then go mod tidy + go mod vendor.

        Modules come from the pack's runtime_dependencies plus the require directives of the
        generated go.mod (generators add per-feature deps there, e.g. one per ext technology).
        """
        go_mod = self._root / "go.mod"
        deps = list(pack.get("runtime_dependencies", {}).get("go", []))
        if go_mod.exists():
            pinned = {d.rsplit("@", 1)[0] for d in deps}
            deps += [
                d for d in _go_mod_requires(go_mod.read_text(encoding="utf-8")) if d.rsplit("@", 1)[0] not in pinned
            ]
        if not deps:
            return []
        if not go_mod.exists():
            warnings.append("Cannot install runtime deps: no go.mod found")
            return []
        rendered = _go_directive(go_mod)
        installed = self._run_go_dep_steps(deps, warnings)
        resolved = _go_directive(go_mod)
        if rendered and resolved and _version_tuple(resolved) > _version_tuple(rendered):
            warnings.append(
                f"go.mod go directive raised from {rendered} to {resolved} by one of the dependencies "
                f"({', '.join(deps)}); building needs Go >= {resolved}"
            )
        return installed

    def _run_go_dep_steps(self, deps: list[str], warnings: list[str]) -> list[str]:
        """go get the deps, then go mod tidy + go mod vendor. Returns deps, or [] on failure."""
        for cmd in (["go", "get", *deps], ["go", "mod", "tidy"], ["go", "mod", "vendor"]):
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(self._root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                warnings.append(f"Failed to install deps ({' '.join(cmd)}): {exc}")
                return []
            if result.returncode != 0:
                warnings.append(f"Failed to install deps ({' '.join(cmd)}): {result.stderr[:200]}")
                return []
        return list(deps)

    def _check_go_builder_image(self, answers: dict[str, str], warnings: list[str]) -> None:
        """Warn when the builder_image answer pins a numeric Go tag older than the go.mod directive.

        The generated Dockerfile sets GOTOOLCHAIN=local, so the builder cannot download a newer Go.
        """
        image = str(answers.get("builder_image") or "").strip()
        reference = image.split("@", 1)[0]  # a digest (@sha256:...) is not a tag
        directive = _go_directive(self._root / "go.mod")
        match = _IMAGE_TAG_VERSION_RE.search(reference)
        if not match or not directive:
            return
        tag = _version_tuple(match.group(1))
        if tag < _version_tuple(directive)[: len(tag)]:
            warnings.append(
                f"builder_image {image} is older than go.mod go {directive}; the Dockerfile sets GOTOOLCHAIN=local, "
                "so the build will fail. Use a builder with Go >= " + directive
            )

    def _post_generate_go(self, written_files: list[Path]) -> list[str]:
        """gofmt generated .go files, then go build + go vet. Returns list of errors."""
        go_files = [str(f) for f in written_files if f.suffix == ".go"]
        if not go_files:
            return []
        errors: list[str] = []
        steps = (["gofmt", "-w", *go_files], ["go", "build", "./..."], ["go", "vet", "./..."])
        for cmd in steps:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(self._root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                errors.append(f"{cmd[0]} not runnable: {exc}")
                continue
            if result.returncode != 0:
                output = (result.stderr or result.stdout).strip()
                errors.append(f"{' '.join(cmd[:2])} failed: {output}")
        return errors

    def _install_runtime_deps(self, pack: dict, warnings: list[str]) -> list[str]:
        """Install runtime dependencies declared in the pack manifest via uv."""
        deps = pack.get("runtime_dependencies", {}).get("python", [])
        if not deps:
            return []

        logger.info("Runtime dependencies needed: %s", ", ".join(deps))

        pyproject = self._root / "pyproject.toml"
        if not pyproject.exists():
            warnings.append("Cannot install runtime deps: no pyproject.toml found")
            return []

        result = subprocess.run(
            ["uv", "add", *deps],
            cwd=str(self._root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            logger.info("Dependencies installed successfully")
            return list(deps)
        else:
            warnings.append(f"Failed to install deps: {result.stderr[:200]}")
            return []

    def _load_pack(self) -> dict | None:
        """Load ignition pack manifest and generator list.

        Auto-detects the single installed pack subdirectory under .ydk/ignition-packs/.
        Also supports legacy .ydk/ignition-pack/ layout for backwards compatibility.
        """
        # New layout: .ydk/ignition-packs/<pack-name>/manifest.yaml
        if self._packs_dir.is_dir():
            subdirs = [d for d in self._packs_dir.iterdir() if d.is_dir()]
            if len(subdirs) > 1:
                names = ", ".join(sorted(d.name for d in subdirs))
                msg = (
                    f"Multiple ignition packs installed ({names}). "
                    "Remove extras so only one remains, or specify which to use."
                )
                raise IgnitionError(msg)
            if len(subdirs) == 1:
                self._pack_dir = subdirs[0]
                manifest_path = self._pack_dir / "manifest.yaml"
                if manifest_path.exists():
                    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return data

        # Legacy layout: .ydk/ignition-pack/manifest.yaml
        legacy_dir = self._root / ".ydk" / "ignition-pack"
        if legacy_dir.is_dir():
            self._pack_dir = legacy_dir
            manifest_path = legacy_dir / "manifest.yaml"
            if manifest_path.exists():
                data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data

        return None

    def _assemble_components(self) -> dict[str, list[dict]]:
        """Read all .ydk/components/, group by type, return as lists."""
        result: dict[str, list[dict]] = {}

        if not self._components_dir.is_dir():
            return result

        for component_type_dir in sorted(self._components_dir.iterdir()):
            if not component_type_dir.is_dir():
                continue
            component_type = component_type_dir.name
            components: list[dict] = []
            for yaml_file in sorted(component_type_dir.rglob("*.yaml")):
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    components.append(data)
            if components:
                result[component_type] = components

        return result

    def _ignite_flat(
        self,
        pack: dict,
        component_data: dict[str, list[dict]],
        init_answers: dict[str, str],
    ) -> tuple[list[GeneratedFile], list[str]]:
        """Run generators as a flat list (original behavior)."""
        all_generated: list[GeneratedFile] = []
        errors: list[str] = []
        generators = pack.get("generators", [])
        for gen_entry in generators:
            script = self._pack_dir / gen_entry["script"]
            if not script.exists():
                errors.append(f"Generator script not found: {script}")
                continue
            try:
                files = self._run_generator(
                    script_path=script,
                    component_data=component_data,
                    output_dir=self._root,
                    init_answers=init_answers,
                )
                all_generated.extend(files)
            except Exception as exc:
                errors.append(f"Generator {gen_entry['script']} failed: {exc}")
        return all_generated, errors

    def _ignite_phased(
        self,
        pack: dict,
        component_data: dict[str, list[dict]],
        init_answers: dict[str, str],
        dry_run: bool,
    ) -> tuple[list[GeneratedFile], list[str]]:
        """Run generators in phased order with artifact passing between phases."""
        all_generated: list[GeneratedFile] = []
        errors: list[str] = []
        exports: dict[str, dict[str, str]] = {}  # phase_id -> {export_name: file_path}

        for phase in pack["phases"]:
            phase_id = phase["id"]
            output_prefix = phase.get("output_prefix", "")

            # Resolve artifact references from prior phases
            artifact_env: dict[str, str] = {}
            for art_name, art_ref in phase.get("artifacts", {}).items():
                # art_ref like "${backend.openapi}" -> resolve
                ref_str = art_ref.strip("${}")
                if "." in ref_str:
                    source_phase, export_name = ref_str.split(".", 1)
                    if source_phase in exports and export_name in exports[source_phase]:
                        artifact_env[f"YDK_ARTIFACT_{art_name.upper()}"] = exports[source_phase][export_name]
                    else:
                        errors.append(
                            f"Phase '{phase_id}': artifact '{art_name}' references '{art_ref}' but export not found"
                        )

            # Determine generator source: pack_ref or local
            if "pack_ref" in phase:
                ref_pack_dir = self._find_installed_pack(phase["pack_ref"])
                if ref_pack_dir is None:
                    errors.append(f"Phase '{phase_id}': referenced pack '{phase['pack_ref']}' not found")
                    continue
                ref_manifest = yaml.safe_load((ref_pack_dir / "manifest.yaml").read_text(encoding="utf-8"))
                phase_generators = ref_manifest.get("generators", [])
                generator_base = ref_pack_dir
            else:
                phase_generators = phase.get("generators", [])
                generator_base = self._pack_dir

            # Run phase generators
            for gen_entry in phase_generators:
                script = generator_base / gen_entry["script"]
                if not script.exists():
                    errors.append(f"Generator script not found: {script}")
                    continue
                try:
                    files = self._run_generator(
                        script_path=script,
                        component_data=component_data,
                        output_dir=self._root,
                        init_answers=init_answers,
                        extra_env=artifact_env if artifact_env else None,
                    )
                    # Prepend output_prefix to file paths
                    for f in files:
                        f.path = output_prefix + f.path
                    all_generated.extend(files)
                except Exception as exc:
                    errors.append(f"Phase '{phase_id}' generator {gen_entry['script']} failed: {exc}")

            # Collect exports
            phase_exports: dict[str, str] = {}
            for export_name, export_path in phase.get("exports", {}).items():
                full_path = self._root / export_path
                if full_path.exists() or dry_run:
                    phase_exports[export_name] = str(full_path)
            exports[phase_id] = phase_exports

        return all_generated, errors

    def _find_installed_pack(self, pack_name: str) -> Path | None:
        """Find an installed pack by name in the catalog or ignition-packs directory."""
        # Check in catalog (source packs)
        catalog_dir = Path(__file__).parent.parent / "catalog" / pack_name
        if catalog_dir.is_dir() and (catalog_dir / "manifest.yaml").exists():
            return catalog_dir

        # Check in project's installed packs
        installed = self._packs_dir / pack_name
        if installed.is_dir() and (installed / "manifest.yaml").exists():
            return installed

        return None

    def _run_generator(
        self,
        script_path: Path,
        component_data: dict[str, list[dict]],
        output_dir: Path,
        init_answers: dict[str, str],
        extra_env: dict[str, str] | None = None,
    ) -> list[GeneratedFile]:
        """Run a single generator as subprocess.

        Env vars in, JSON stdout out.
        """
        env_vars = {
            "YDK_PROJECT_ROOT": str(output_dir),
            "YDK_OUTPUT_DIR": str(output_dir),
            "YDK_INIT_ANSWERS": json.dumps(init_answers),
        }

        # Write assembled component data to temp files and pass paths as env vars
        temp_files: list[Path] = []
        try:
            for comp_type, components in component_data.items():
                fd, tmp_str = tempfile.mkstemp(suffix=".yaml", prefix=f"ydk_{comp_type}_")
                os.close(fd)
                tmp = Path(tmp_str)
                tmp.write_text(yaml.dump(components, default_flow_style=False, sort_keys=False), encoding="utf-8")
                temp_files.append(tmp)
                env_key = f"YDK_COMPONENTS_{comp_type.upper()}"
                env_vars[env_key] = str(tmp)

                # Singleton unwrapping: if exactly 1 component, also provide singular form
                if len(components) == 1:
                    singular_key = f"YDK_COMPONENT_{comp_type.upper()}"
                    fd2, tmp_str2 = tempfile.mkstemp(suffix=".yaml", prefix=f"ydk_{comp_type}_singular_")
                    os.close(fd2)
                    tmp2 = Path(tmp_str2)
                    tmp2.write_text(
                        yaml.dump(components[0], default_flow_style=False, sort_keys=False), encoding="utf-8"
                    )
                    temp_files.append(tmp2)
                    env_vars[singular_key] = str(tmp2)

            # Add extra env vars (artifacts from prior phases)
            if extra_env:
                env_vars.update(extra_env)

            try:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_GENERATOR_TIMEOUT,
                    env={**dict(os.environ), **env_vars},
                )
            except subprocess.TimeoutExpired as exc:
                msg = f"Generator {script_path.name} timed out after {_GENERATOR_TIMEOUT}s"
                raise IgnitionError(msg) from exc

            if result.returncode != 0:
                msg = f"Generator exited with code {result.returncode}: {result.stderr}"
                raise IgnitionError(msg)

            if result.stderr and result.stderr.strip():
                logger.warning("Generator %s stderr: %s", script_path.name, result.stderr.strip())

            stdout = result.stdout.strip()
            if not stdout:
                return []

            raw = json.loads(stdout)
            if not isinstance(raw, list):
                msg = f"Generator output must be a JSON array, got: {type(raw).__name__}"
                raise IgnitionError(msg)

            return [GeneratedFile(path=item["path"], content=item["content"]) for item in raw]

        finally:
            for tmp in temp_files:
                tmp.unlink(missing_ok=True)

    def _filter_files(
        self,
        all_files: list[GeneratedFile],
        state: ScaffoldState,
        *,
        force: bool,
        warnings: list[str],
    ) -> tuple[list[GeneratedFile], int]:
        """Filter files: skip unchanged hashes and developer-owned files."""
        to_write: list[GeneratedFile] = []
        skipped = 0

        for gf in all_files:
            # Check developer ownership (unless --force)
            if not force and state.is_developer_owned(gf.path, self._root):
                warnings.append(f"Skipped developer-owned file: {gf.path}")
                skipped += 1
                continue

            # Compute the content as it will actually be written
            effective_content = gf.content

            # Check hash unchanged (force bypasses hash check too)
            if not force and not state.is_modified(gf.path, effective_content):
                skipped += 1
                continue

            to_write.append(gf)

        return to_write, skipped

    def _is_untracked_edit(self, gf: GeneratedFile, state: ScaffoldState) -> bool:
        """True when *gf* exists on disk without a recorded hash and its content differs."""
        full = self._root / gf.path
        if state.has_hash(gf.path) or not full.is_file():
            return False
        return full.read_text(encoding="utf-8", errors="replace") != gf.content

    def _register_todos(self, files: list[GeneratedFile]) -> int:
        """Scan generated files for raise NotImplementedError, register with TodoManager.

        Uses AST-based scan_file to extract enclosing method names for each TODO.
        Falls back to inline content scanning if the file doesn't exist on disk.
        """
        import ast

        from ydk.core.todo_manager import TodoManager, go_enclosing_func, markers_for

        todo_mgr = TodoManager(self._root)
        existing = {t.id for t in todo_mgr.list_todos()}
        for gf in files:
            markers: list[dict] = []
            found = markers_for(gf.path)
            if found and not gf.path.endswith(".py"):
                stmts, comment_prefix = found
                content_lines = gf.content.splitlines()
                for i, line in enumerate(content_lines, start=1):
                    stripped = line.strip()
                    if stripped.startswith(stmts):
                        comment = ""
                        if comment_prefix in stripped:
                            comment = stripped.split(comment_prefix, 1)[1].strip()
                        method = go_enclosing_func(content_lines, i) if gf.path.endswith(".go") else "<unknown>"
                        markers.append({"line": i, "method": method, "description": comment})
                _reconcile(todo_mgr, gf.path, markers)
                continue
            if not gf.path.endswith(".py"):
                continue
            # Prefer scan_file (reads from disk with full AST parsing)
            full_path = self._root / gf.path
            if full_path.exists():
                findings = todo_mgr.scan_file(gf.path)
                markers.extend(
                    {
                        "line": finding["line"],
                        "method": finding["method_name"],
                        "description": finding.get("comment", ""),
                    }
                    for finding in findings
                )
            else:
                # Fallback: scan content directly with AST for method context
                lines = gf.content.splitlines()
                method_ranges: list[tuple[str, int, int]] = []
                try:
                    tree = ast.parse(gf.content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            for item in node.body:
                                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    end = item.end_lineno or item.lineno
                                    method_ranges.append((f"{node.name}.{item.name}", item.lineno, end))
                        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not any(
                            node.lineno >= s and node.lineno <= e for _, s, e in method_ranges
                        ):
                            end = node.end_lineno or node.lineno
                            method_ranges.append((node.name, node.lineno, end))
                except SyntaxError:
                    pass

                for i, line in enumerate(lines, start=1):
                    stripped = line.strip()
                    if stripped.startswith(_TODO_PATTERN):
                        # Find enclosing method
                        method = "<unknown>"
                        for mname, start, end in method_ranges:
                            if start <= i <= end:
                                method = mname
                                break
                        comment = ""
                        if "#" in stripped:
                            comment = stripped.split("#", 1)[1].strip()
                        # If no inline comment, look for IMPLEMENT comment on preceding lines
                        if not comment:
                            comment = self._extract_implement_comment(lines, i)
                        markers.append({"line": i, "method": method, "description": comment})
            _reconcile(todo_mgr, gf.path, markers)
        # reconcile() keeps existing entries for moved markers; count only new ones.
        return len({t.id for t in todo_mgr.list_todos()} - existing)

    @staticmethod
    def _extract_implement_comment(lines: list[str], raise_line: int) -> str:
        """Extract IMPLEMENT comment from lines preceding a raise NotImplementedError.

        Looks backwards from the raise line for '# IMPLEMENT:' comments.
        """
        for offset in range(1, 10):
            idx = raise_line - 1 - offset  # lines is 0-indexed, raise_line is 1-indexed
            if idx < 0:
                break
            line = lines[idx].strip()
            if line.startswith("# IMPLEMENT:"):
                return line[len("# IMPLEMENT:") :].strip()
            if line.startswith("# YDK-TODO:"):
                # Found the TODO marker but no IMPLEMENT — stop looking
                break
            if not line.startswith("#"):
                # Hit non-comment code — stop looking
                break
        return ""

    def _detect_conflicts(self, all_generated: list[GeneratedFile]) -> list[str]:
        """Detect when multiple generators produce the same output path."""
        seen: dict[str, int] = {}
        conflicts: list[str] = []
        for i, gf in enumerate(all_generated):
            if gf.path in seen:
                conflicts.append(f"Conflict: '{gf.path}' produced by generators at index {seen[gf.path]} and {i}")
            else:
                seen[gf.path] = i
        return conflicts

    def _post_generate(self, written_files: list[Path]) -> list[str]:
        """Run quality checks on generated files. Returns list of errors."""
        errors: list[str] = []

        # 1. Python syntax check
        for f in written_files:
            if f.suffix == ".py":
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(f)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode != 0:
                    errors.append(f"Syntax error in {f.name}: {result.stderr.strip()}")

        # 2. Circular import detection
        cycles = self._detect_import_cycles(written_files)
        for cycle in cycles:
            logger.warning("Circular import detected: %s", cycle)

        # 3. Ruff format (best-effort, don't fail ignition)
        py_files = [str(f) for f in written_files if f.suffix == ".py"]
        if py_files:
            subprocess.run(
                ["ruff", "format", *py_files],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        return errors

    def _detect_import_cycles(self, files: list[Path]) -> list[str]:
        """Build import graph from generated files, detect cycles via DFS."""
        import ast

        # Map module name -> set of imported module names
        # Use path relative to project root for consistent naming
        graph: dict[str, set[str]] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            try:
                rel = f.resolve().relative_to(self._root)
            except ValueError:
                rel = f
            module = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
            imports: set[str] = set()
            try:
                tree = ast.parse(f.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".")[0])
            except SyntaxError:
                continue
            graph[module] = imports

        # DFS cycle detection
        cycles: list[str] = []
        visited: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> None:
            if node in path:
                cycle_start = path.index(node)
                cycles.append(" -> ".join([*path[cycle_start:], node]))
                return
            if node in visited:
                return
            path.append(node)
            for neighbor in graph.get(node, set()):
                if neighbor in graph:
                    dfs(neighbor)
            path.pop()
            visited.add(node)

        for node in graph:
            dfs(node)

        return cycles
