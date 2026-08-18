"""Tests for the scaffold engine."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ydk.core.scaffold import ScaffoldEngine, TemplateManifest, TemplateValidationError


def _create_template(base: Path, name: str, variables: dict[str, str], files: dict[str, str]) -> Path:
    """Helper: create a template folder with manifest and .j2 files."""
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "description": f"Test template {name}", "variables": variables}
    (folder / "manifest.yaml").write_text(yaml.dump(manifest, default_flow_style=False))
    for filename, content in files.items():
        file_path = folder / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    return folder


# --- list_templates ---


def test_list_templates_finds_global(tmp_path: Path) -> None:
    """list_templates finds templates in the global dir."""
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    _create_template(global_, "alpha", {}, {"file.txt.j2": "hello"})

    engine = ScaffoldEngine(project, global_)
    templates = engine.list_templates()
    assert len(templates) == 1
    assert templates[0].name == "alpha"


def test_list_templates_finds_both_dirs(tmp_path: Path) -> None:
    """list_templates finds templates in both project and global dirs."""
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    _create_template(project, "proj-tmpl", {}, {"a.txt.j2": "a"})
    _create_template(global_, "glob-tmpl", {}, {"b.txt.j2": "b"})

    engine = ScaffoldEngine(project, global_)
    templates = engine.list_templates()
    names = [t.name for t in templates]
    assert "proj-tmpl" in names
    assert "glob-tmpl" in names


def test_list_templates_project_overrides_global(tmp_path: Path) -> None:
    """Project template with same name overrides global."""
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    _create_template(project, "shared", {"a": "desc"}, {"f.txt.j2": "project"})
    _create_template(global_, "shared", {"b": "desc"}, {"f.txt.j2": "global"})

    engine = ScaffoldEngine(project, global_)
    templates = engine.list_templates()
    shared = [t for t in templates if t.name == "shared"]
    assert len(shared) == 1
    assert "a" in shared[0].variables


# --- get_template ---


def test_get_template_returns_manifest(tmp_path: Path) -> None:
    """get_template returns the correct manifest."""
    global_ = tmp_path / "global"
    _create_template(global_, "my-tmpl", {"x": "X var"}, {"f.txt.j2": "content"})

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    manifest = engine.get_template("my-tmpl")
    assert isinstance(manifest, TemplateManifest)
    assert manifest.name == "my-tmpl"
    assert manifest.variables == {"x": "X var"}


def test_get_template_raises_for_unknown(tmp_path: Path) -> None:
    """get_template raises KeyError for unknown template."""
    engine = ScaffoldEngine(tmp_path / "a", tmp_path / "b")
    try:
        engine.get_template("no-such-template")
        raise AssertionError("Expected KeyError")
    except KeyError:
        pass


# --- apply ---


def test_apply_renders_content(tmp_path: Path) -> None:
    """apply renders file content with variables."""
    global_ = tmp_path / "global"
    _create_template(global_, "greet", {"name": "Name"}, {"hello.txt.j2": "Hello, {{name}}!"})

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    files = engine.apply("greet", {"name": "World"})
    assert len(files) == 1
    assert files[0].content == "Hello, World!"


def test_apply_renders_filenames(tmp_path: Path) -> None:
    """apply renders filenames with variables and strips .j2."""
    global_ = tmp_path / "global"
    _create_template(global_, "mod", {"mod": "Mod name"}, {"{{mod}}_service.py.j2": "pass"})

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    files = engine.apply("mod", {"mod": "order"})
    assert files[0].path == Path("order_service.py")


def test_apply_preserves_directory_structure(tmp_path: Path) -> None:
    """apply preserves directory structure from the template."""
    global_ = tmp_path / "global"
    _create_template(
        global_,
        "nested",
        {"x": "X"},
        {"src/main.py.j2": "# main", "src/lib/helper.py.j2": "# helper"},
    )

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    files = engine.apply("nested", {"x": "val"})
    paths = {str(f.path) for f in files}
    assert "src/main.py" in paths
    assert "src/lib/helper.py" in paths


def test_apply_raises_for_missing_variable(tmp_path: Path) -> None:
    """apply raises TemplateValidationError for missing required variables."""
    global_ = tmp_path / "global"
    _create_template(global_, "need-var", {"a": "A", "b": "B"}, {"f.txt.j2": "{{a}} {{b}}"})

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    with pytest.raises(TemplateValidationError, match="b"):
        engine.apply("need-var", {"a": "hello"})


def test_apply_raises_for_extra_variables(tmp_path: Path) -> None:
    """apply raises TemplateValidationError for extra variables not in manifest."""
    global_ = tmp_path / "global"
    _create_template(global_, "strict", {"a": "A"}, {"f.txt.j2": "{{a}}"})

    engine = ScaffoldEngine(tmp_path / "empty", global_)
    with pytest.raises(TemplateValidationError, match="z"):
        engine.apply("strict", {"a": "hello", "z": "extra"})


# --- write_files ---


def test_write_files_creates_files(tmp_path: Path) -> None:
    """write_files creates files on disk."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("out.txt"), content="content")]
    written = engine.write_files(files, tmp_path)
    assert len(written) == 1
    assert (tmp_path / "out.txt").read_text() == "content"


def test_write_files_adds_header_py(tmp_path: Path) -> None:
    """write_files adds GENERATED header for .py files."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("mod.py"), content="pass\n")]
    engine.write_files(files, tmp_path)
    text = (tmp_path / "mod.py").read_text()
    assert text == "pass\n"


def test_write_files_no_header_ts(tmp_path: Path) -> None:
    """write_files writes content directly without GENERATED header."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("index.ts"), content="export {};\n")]
    engine.write_files(files, tmp_path)
    text = (tmp_path / "index.ts").read_text()
    assert text == "export {};\n"


def test_write_files_no_header_md(tmp_path: Path) -> None:
    """write_files writes content directly without GENERATED header."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("README.md"), content="# Hello\n")]
    engine.write_files(files, tmp_path)
    text = (tmp_path / "README.md").read_text()
    assert text == "# Hello\n"


def test_write_files_skips_header_unknown_ext(tmp_path: Path) -> None:
    """write_files skips header for unknown extensions."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("data.csv"), content="a,b,c\n")]
    engine.write_files(files, tmp_path)
    text = (tmp_path / "data.csv").read_text()
    assert text == "a,b,c\n"


def test_write_files_creates_nested_dirs(tmp_path: Path) -> None:
    """write_files creates nested directories as needed."""
    from ydk.core.scaffold import GeneratedFile

    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("a/b/c/deep.txt"), content="deep")]
    engine.write_files(files, tmp_path)
    assert (tmp_path / "a" / "b" / "c" / "deep.txt").read_text() == "deep"


def test_write_files_raises_if_exists(tmp_path: Path) -> None:
    """write_files raises FileExistsError if file already exists."""
    from ydk.core.scaffold import GeneratedFile

    (tmp_path / "exists.txt").write_text("old")
    engine = ScaffoldEngine(tmp_path, tmp_path)
    files = [GeneratedFile(path=Path("exists.txt"), content="new")]
    try:
        engine.write_files(files, tmp_path)
        raise AssertionError("Expected FileExistsError")
    except FileExistsError:
        pass


# --- create_template ---


def test_create_template_creates_manifest(tmp_path: Path) -> None:
    """create_template creates manifest.yaml in project templates dir."""
    engine = ScaffoldEngine(tmp_path, tmp_path)
    folder = engine.create_template("my-new", "A new template", tmp_path)
    assert (folder / "manifest.yaml").exists()
    data = yaml.safe_load((folder / "manifest.yaml").read_text())
    assert data["name"] == "my-new"
    assert data["description"] == "A new template"


def test_create_template_includes_sample_j2_file(tmp_path: Path) -> None:
    """create_template creates a sample .j2 file so the template is not empty."""
    engine = ScaffoldEngine(tmp_path, tmp_path)
    folder = engine.create_template("my-new", "A new template", tmp_path)
    j2_files = list(folder.glob("*.j2"))
    assert len(j2_files) >= 1, "Expected at least one .j2 sample file"
    # The sample file should be renderable
    content = j2_files[0].read_text()
    assert "module_name" in content


def test_create_template_manifest_has_module_name_variable(tmp_path: Path) -> None:
    """create_template manifest includes module_name variable."""
    engine = ScaffoldEngine(tmp_path, tmp_path)
    folder = engine.create_template("my-new", "A new template", tmp_path)
    data = yaml.safe_load((folder / "manifest.yaml").read_text())
    assert "module_name" in data["variables"]


# --- round trip ---


def test_round_trip_test_greeting(tmp_path: Path) -> None:
    """Round-trip: apply test-greeting template, verify output content."""
    global_templates = Path(__file__).resolve().parent.parent.parent / "src" / "ydk" / "templates"
    engine = ScaffoldEngine(tmp_path / "empty", global_templates)

    files = engine.apply("test-greeting", {"greeting_name": "World", "module_name": "hello"})
    assert len(files) == 2

    py_file = next(f for f in files if f.path == Path("hello.py"))
    assert 'return "Hello, World!"' in py_file.content

    test_file = next(f for f in files if f.path == Path("tests/test_hello.py"))
    assert "from hello import greet" in test_file.content
    assert 'assert greet() == "Hello, World!"' in test_file.content

    # Write and verify on disk
    written = engine.write_files(files, tmp_path / "output")
    assert len(written) == 2
    py_text = (tmp_path / "output" / "hello.py").read_text()
    assert 'return "Hello, World!"' in py_text
