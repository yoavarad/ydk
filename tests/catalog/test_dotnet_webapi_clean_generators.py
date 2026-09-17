"""Tests for dotnet-webapi-clean's domain-entities and efcore-dbcontext generators.

Runs the generator scripts as subprocesses exactly as `ignition.py`'s `_run_generator`
does (env vars in, JSON array on stdout out), against inline sample entity data.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

PACK_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk" / "catalog" / "dotnet-webapi-clean"
GENERATORS_DIR = PACK_ROOT / "generators"

ITEM_ENTITY: dict = {
    "$schema": "ydk:schema:entity",
    "id": "ydk:entity:sample/Item",
    "description": "Sample item entity",
    "fields": {
        "id": {"type": "integer", "primary_key": True, "generated": True, "description": "PK"},
        "name": {"type": "string", "required": True, "max_length": 200, "description": "Item name"},
        "description": {"type": "text", "required": False, "description": "Optional description"},
        "price": {"type": "Decimal", "required": True, "precision": [10, 2], "description": "Item price"},
        "is_active": {"type": "boolean", "required": True, "description": "Active flag"},
        "created_at": {"type": "datetime", "required": True, "auto": True, "description": "Creation time"},
        "category_id": {
            "type": "integer",
            "required": False,
            "nullable": True,
            "index": True,
            "description": "Optional category FK",
        },
    },
}


def _run_generator(script_name: str, entities: list[dict], project_root: Path) -> list[dict]:
    """Invoke a generator script the way ignition.py does: env vars in, JSON stdout out."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        yaml.dump(entities, fh)
        entities_path = fh.name

    env = {
        "YDK_COMPONENTS_ENTITY": entities_path,
        "YDK_PROJECT_ROOT": str(project_root),
        "YDK_OUTPUT_DIR": str(project_root),
        "YDK_INIT_ANSWERS": "{}",
    }
    import os

    result = subprocess.run(
        [sys.executable, str(GENERATORS_DIR / script_name)],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"{script_name} failed: {result.stderr}"
    return json.loads(result.stdout)


class TestDomainEntitiesGenerator:
    def test_emits_one_file_per_entity(self, tmp_path: Path) -> None:
        files = _run_generator("domain_entities.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        assert len(files) == 1
        assert files[0]["path"] == "Domain/Entities/Item.cs"

    def test_maps_canonical_types_to_csharp(self, tmp_path: Path) -> None:
        files = _run_generator("domain_entities.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        content = files[0]["content"]
        assert "public int Id { get; set; }" in content
        assert "public string Name { get; set; } = string.Empty;" in content
        assert "public string? Description { get; set; }" in content
        assert "public decimal Price { get; set; }" in content
        assert "public bool IsActive { get; set; }" in content
        assert "public DateTime CreatedAt { get; set; }" in content
        assert "public int? CategoryId { get; set; }" in content

    def test_namespace_derived_from_project_root(self, tmp_path: Path) -> None:
        files = _run_generator("domain_entities.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        assert "namespace MyWebapi.Domain.Entities;" in files[0]["content"]

    def test_output_is_valid_json_array_of_path_content(self, tmp_path: Path) -> None:
        files = _run_generator("domain_entities.py", [ITEM_ENTITY], tmp_path / "proj")
        assert isinstance(files, list)
        for f in files:
            assert set(f.keys()) == {"path", "content"}

    def test_empty_entities_emits_no_files(self, tmp_path: Path) -> None:
        files = _run_generator("domain_entities.py", [], tmp_path / "proj")
        assert files == []


class TestEfCoreDbContextGenerator:
    def test_emits_dbcontext_and_one_configuration_per_entity(self, tmp_path: Path) -> None:
        files = _run_generator("efcore_dbcontext.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        paths = [f["path"] for f in files]
        assert "Infrastructure/Persistence/AppDbContext.cs" in paths
        assert "Infrastructure/Persistence/Configurations/ItemConfiguration.cs" in paths
        assert len(files) == 2

    def test_dbcontext_has_dbset_and_sqlite_setup(self, tmp_path: Path) -> None:
        files = _run_generator("efcore_dbcontext.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        dbcontext = next(f for f in files if f["path"].endswith("AppDbContext.cs"))["content"]
        assert "public DbSet<Item> Items => Set<Item>();" in dbcontext
        assert "UseSqlite(" in dbcontext
        assert "ApplyConfigurationsFromAssembly" in dbcontext

    def test_configuration_has_key_and_required_fields(self, tmp_path: Path) -> None:
        files = _run_generator("efcore_dbcontext.py", [ITEM_ENTITY], tmp_path / "my-webapi")
        config = next(f for f in files if f["path"].endswith("ItemConfiguration.cs"))["content"]
        assert "IEntityTypeConfiguration<Item>" in config
        assert "builder.HasKey(x => x.Id);" in config
        assert "builder.Property(x => x.Name).IsRequired().HasMaxLength(200);" in config
        assert "builder.Property(x => x.Price).IsRequired().HasPrecision(10, 2);" in config
        # Optional/nullable fields get no fluent config (no IsRequired chain).
        assert "x.Description)" not in config
        assert "x.CategoryId)" not in config

    def test_empty_entities_still_emits_dbcontext_with_no_dbsets(self, tmp_path: Path) -> None:
        files = _run_generator("efcore_dbcontext.py", [], tmp_path / "proj")
        assert len(files) == 1
        assert files[0]["path"] == "Infrastructure/Persistence/AppDbContext.cs"
        assert "DbSet<" not in files[0]["content"]

    def test_entity_without_primary_key_fails_loudly(self, tmp_path: Path) -> None:
        no_pk_entity = {
            "id": "ydk:entity:sample/Widget",
            "fields": {"name": {"type": "string", "required": True, "description": "name"}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
            yaml.dump([no_pk_entity], fh)
            entities_path = fh.name

        env = {
            "YDK_COMPONENTS_ENTITY": entities_path,
            "YDK_PROJECT_ROOT": str(tmp_path / "proj"),
            "YDK_OUTPUT_DIR": str(tmp_path / "proj"),
            "YDK_INIT_ANSWERS": "{}",
        }
        import os

        result = subprocess.run(
            [sys.executable, str(GENERATORS_DIR / "efcore_dbcontext.py")],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            timeout=30,
            check=False,
        )
        assert result.returncode != 0
        assert "primary_key" in result.stderr


class TestTemplatesExist:
    @pytest.mark.parametrize(
        "template_path",
        [
            "domain/entity.cs.j2",
            "infrastructure/dbcontext.cs.j2",
            "infrastructure/entity_configuration.cs.j2",
        ],
    )
    def test_template_file_exists(self, template_path: str) -> None:
        assert (PACK_ROOT / "templates" / template_path).is_file()
