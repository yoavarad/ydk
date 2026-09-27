"""Tests for model-tier configuration: the single source of truth for Claude model IDs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from ydk.models.config import DEFAULT_MODEL_TIERS, AIConfig, SpecCheckConfig, YdkConfig

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk"
REPO_CONFIG = Path(__file__).resolve().parents[2] / ".ydk" / "config.yaml"


class TestModelTierDefaults:
    def test_default_tiers_are_current_first_party_ids(self) -> None:
        assert AIConfig().model_tiers == {
            "fast": "claude-haiku-4-5",
            "review": "claude-sonnet-5",
            "deep": "claude-opus-5",
        }
        assert AIConfig().model_tiers == DEFAULT_MODEL_TIERS

    def test_default_tiers_not_shared_between_instances(self) -> None:
        a = AIConfig()
        a.model_tiers["fast"] = "changed"
        assert AIConfig().model_tiers["fast"] == "claude-haiku-4-5"
        assert DEFAULT_MODEL_TIERS["fast"] == "claude-haiku-4-5"


class TestModelFor:
    def test_returns_configured_tier(self) -> None:
        cfg = AIConfig(model_tiers={"review": "claude-custom"})
        assert cfg.model_for("review") == "claude-custom"

    def test_partial_override_falls_back_to_default_tier(self) -> None:
        cfg = AIConfig(model_tiers={"review": "claude-custom"})
        assert cfg.model_for("fast") == "claude-haiku-4-5"
        assert cfg.model_for("deep") == "claude-opus-5"

    def test_unknown_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown model tier"):
            AIConfig().model_for("nope")


class TestSpecCheckModelRemoved:
    def test_spec_check_has_no_model_field(self) -> None:
        assert "model" not in SpecCheckConfig.model_fields

    def test_legacy_spec_check_model_key_still_loads(self) -> None:
        cfg = YdkConfig.model_validate(
            {"project": {"name": "x"}, "spec_check": {"model": "us.anthropic.claude-sonnet-4-6", "timeout": 30}}
        )
        assert cfg.spec_check.timeout == 30


class TestAutoExtractRemoved:
    def test_memory_has_no_auto_extract_field(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}, "memory": {"auto_extract": True}})
        assert not hasattr(cfg.memory, "auto_extract")


class TestSingleSourceOfTruth:
    def test_no_claude_model_ids_in_src_outside_models_config(self) -> None:
        pattern = re.compile(r"claude-(?:haiku|sonnet|opus|fable)-\d")
        offenders = [
            str(p.relative_to(SRC_ROOT))
            for p in SRC_ROOT.rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".yaml", ".yml", ".md"}
            and p != SRC_ROOT / "models" / "config.py"
            and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
        ]
        assert offenders == []

    def test_repo_config_has_no_bedrock_or_hardcoded_model(self) -> None:
        text = REPO_CONFIG.read_text(encoding="utf-8")
        assert "us.anthropic." not in text
        raw = yaml.safe_load(text)
        assert "model" not in raw.get("spec_check", {})
