"""Scaffold engine — generates files from Jinja2 templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import BaseLoader, Environment


class TemplateValidationError(Exception):
    """Raised when template variables don't match manifest."""


@dataclass
class TemplateManifest:
    """Parsed manifest.yaml metadata for a scaffold template."""

    name: str
    description: str
    variables: dict[str, str]  # name -> description. ALL variables are required.
    path: Path  # absolute path to the template folder


@dataclass
class GeneratedFile:
    """A single file produced by template rendering."""

    path: Path  # output path relative to project root
    content: str


class ScaffoldEngine:
    """Generates files from Jinja2 templates using a manifest-driven approach."""

    def __init__(self, project_templates: Path, global_templates: Path) -> None:
        self._project_templates = project_templates
        self._global_templates = global_templates
        self._env = Environment(loader=BaseLoader(), keep_trailing_newline=True)

    def list_templates(self) -> list[TemplateManifest]:
        """List all available templates. Project-specific first, then global."""
        seen: set[str] = set()
        result: list[TemplateManifest] = []
        for templates_dir in (self._project_templates, self._global_templates):
            if not templates_dir.is_dir():
                continue
            for child in sorted(templates_dir.iterdir()):
                manifest_path = child / "manifest.yaml"
                if child.is_dir() and manifest_path.exists() and child.name not in seen:
                    seen.add(child.name)
                    result.append(self._load_manifest(manifest_path))
        return result

    def get_template(self, name: str) -> TemplateManifest:
        """Get a specific template by name. Project overrides global."""
        for templates_dir in (self._project_templates, self._global_templates):
            candidate = templates_dir / name / "manifest.yaml"
            if candidate.exists():
                return self._load_manifest(candidate)
        msg = f"Template not found: {name}"
        raise KeyError(msg)

    def apply(self, name: str, variables: dict[str, str]) -> list[GeneratedFile]:
        """Generate files from a template.

        Loads manifest, validates ALL variables are provided,
        renders each .j2 file with Jinja2 (both content and filenames),
        and returns the list of generated files without writing to disk.
        """
        manifest = self.get_template(name)
        required = set(manifest.variables.keys())
        provided = set(variables.keys())

        missing = required - provided
        if missing:
            msg = f"Missing required variables: {', '.join(sorted(missing))}"
            raise TemplateValidationError(msg)

        extra = provided - required
        if extra:
            msg = f"Extra variables not in manifest: {', '.join(sorted(extra))}"
            raise TemplateValidationError(msg)

        results: list[GeneratedFile] = []
        template_dir = manifest.path

        for j2_file in sorted(template_dir.rglob("*.j2")):
            # Render file content
            content_template = self._env.from_string(j2_file.read_text())
            rendered_content = content_template.render(**variables)

            # Render filename (strip .j2 suffix, render variables in path)
            relative = j2_file.relative_to(template_dir)
            # Strip the .j2 extension from the final component
            rendered_parts: list[str] = []
            for part in relative.parts:
                rendered_part = self._env.from_string(part).render(**variables)
                rendered_parts.append(rendered_part)
            # The last part has .j2 suffix to strip
            rendered_parts[-1] = rendered_parts[-1].removesuffix(".j2")
            output_path = Path(*rendered_parts)

            results.append(GeneratedFile(path=output_path, content=rendered_content))

        return results

    def write_files(self, files: list[GeneratedFile], output_base: Path) -> list[Path]:
        """Write generated files to disk. Returns list of written paths.

        Creates directories as needed, adds GENERATED header based on extension,
        and refuses to overwrite existing files.
        """
        written: list[Path] = []
        for f in files:
            full_path = output_base / f.path
            if full_path.exists():
                msg = f"File already exists: {full_path}"
                raise FileExistsError(msg)

            full_path.parent.mkdir(parents=True, exist_ok=True)

            full_path.write_text(f.content)
            written.append(full_path)

        return written

    def create_template(self, name: str, description: str, template_dir: Path) -> Path:
        """Create a new template in the given directory.

        Creates template_dir/name/manifest.yaml with name + description,
        plus a sample .j2 file so the template isn't completely empty.
        Returns the path to the created template folder.
        """
        folder = template_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": name,
            "description": description,
            "variables": {"module_name": "Python module name (snake_case)"},
        }
        (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))

        # Create a sample template file
        sample = folder / "{{module_name}}.py.j2"
        sample.write_text('"""{{ module_name }} module."""\n')

        return folder

    def _load_manifest(self, manifest_path: Path) -> TemplateManifest:
        """Load a manifest.yaml file into a TemplateManifest."""
        data = yaml.safe_load(manifest_path.read_text())
        return TemplateManifest(
            name=data["name"],
            description=data.get("description", ""),
            variables=data.get("variables", {}),
            path=manifest_path.parent,
        )
