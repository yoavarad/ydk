"""Tests for model-tier configuration: the single source of truth for Claude model IDs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ydk.models.config import DEFAULT_MODEL_TIERS, AIConfig, SpecCheckConfig, YdkConfig

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ydk"
REPO_CONFIG = Path(__file__).resolve().parents[2] / ".ydk" / "config.yaml"


class TestModelTierDefaults:
    def test_default_tiers_are_current_first_party_ids(self) -> None:
        assert AIConfig().model_tiers == {
            "fast": "claude-haiku-4-5",
            "review": "claude-sonnet-5",
            "deep": "claude-opus-5-5",
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
        assert cfg.model_for("deep") == "claude-opus-5-5"

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


class TestPrBodyConfig:
    def test_default_ui_exclude_is_graphify_out(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}})
        assert cfg.verification.pr_body.ui_exclude == ["graphify-out/**"]

    def test_user_list_replaces_default(self) -> None:
        cfg = YdkConfig.model_validate(
            {"project": {"name": "x"}, "verification": {"pr_body": {"ui_exclude": ["docs/**"]}}}
        )
        assert cfg.verification.pr_body.ui_exclude == ["docs/**"]

    def test_unknown_pr_body_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"pr_body": {"bogus": 1}}})


class TestGoVerificationConfig:
    def test_defaults(self) -> None:
        go = YdkConfig.model_validate({"project": {"name": "x"}}).verification.go
        assert go.coverage_min == 0.0
        assert go.coverage_packages == []
        assert go.test_tags == []
        assert go.race is True

    def test_values_set(self) -> None:
        cfg = YdkConfig.model_validate(
            {
                "project": {"name": "x"},
                "verification": {
                    "go": {
                        "coverage_min": 80,
                        "coverage_packages": ["internal/censor", "internal/store"],
                        "test_tags": ["integration"],
                        "race": False,
                    }
                },
            }
        )
        go = cfg.verification.go
        assert go.coverage_min == 80.0
        assert go.coverage_packages == ["internal/censor", "internal/store"]
        assert go.test_tags == ["integration"]
        assert go.race is False

    @pytest.mark.parametrize("bad", [-1, 100.5])
    def test_coverage_min_out_of_range_rejected(self, bad: float) -> None:
        with pytest.raises(ValueError, match="coverage_min"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"go": {"coverage_min": bad}}})

    def test_skip_patterns_default_matches_unreasoned_skip_only(self) -> None:
        import re

        patterns = YdkConfig.model_validate({"project": {"name": "x"}}).verification.go.skip_patterns
        for bad in (
            "\tt.Skip()",
            "\tt.SkipNow()",
            '\tt.Skip("")',
            '\tt.Skipf("")',
            "\tb.Skip()",
            "\ttb.SkipNow()",
            "\ts.T().Skip()",
        ):
            assert any(re.search(p, bad) for p in patterns), bad
        for ok in ('\tt.Skip("needs db")', '\tt.Skipf("needs %s", x)', "\tt.Skipped()", '\ts.T().Skip("x")'):
            assert not any(re.search(p, ok) for p in patterns), ok

    def test_invalid_skip_pattern_rejected(self) -> None:
        with pytest.raises(ValueError, match="skip_patterns"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"go": {"skip_patterns": ["("]}}})

    def test_unknown_go_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"go": {"bogus": 1}}})


class TestDotnetTargetConfig:
    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_target_rejected(self, blank: str) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"dotnet": {"target": blank}}})

    def test_unknown_dotnet_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"dotnet": {"bogus": 1}}})

    def test_default_target_is_none(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}})
        assert cfg.verification.dotnet.target is None

    def test_target_set(self) -> None:
        cfg = YdkConfig.model_validate(
            {"project": {"name": "x"}, "verification": {"dotnet": {"target": "src/App.sln"}}}
        )
        assert cfg.verification.dotnet.target == "src/App.sln"


class TestProofConfig:
    def test_default_screenshot_patterns_unchanged(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}})
        assert cfg.proof.screenshot_ref_patterns == ["ydk:page:*", "ydk:route:*"]

    def test_custom_screenshot_patterns(self) -> None:
        cfg = YdkConfig.model_validate(
            {"project": {"name": "x"}, "proof": {"screenshot_ref_patterns": ["ydk:page:*", "ydk:component:*"]}}
        )
        assert cfg.proof.screenshot_ref_patterns == ["ydk:page:*", "ydk:component:*"]


class TestTddConfig:
    def test_defaults_are_legacy(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}})
        tdd = cfg.verification.tdd
        assert tdd.source_globs is None
        assert tdd.test_globs is None
        assert tdd.exempt_globs == []
        assert tdd.test_for == "python-tests-dir"
        assert tdd.test_suffix == "_test.go"

    def test_go_config(self) -> None:
        cfg = YdkConfig.model_validate(
            {
                "project": {"name": "x"},
                "verification": {"tdd": {"source_globs": ["**/*.go"], "test_for": "same-dir-suffix"}},
            }
        )
        assert cfg.verification.tdd.test_for == "same-dir-suffix"

    def test_unknown_strategy_rejected(self) -> None:
        with pytest.raises(ValueError, match="test_for"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"tdd": {"test_for": "bogus"}}})

    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="bogus"):
            YdkConfig.model_validate({"project": {"name": "x"}, "verification": {"tdd": {"bogus": 1}}})

    def test_default_test_commands(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}})
        assert cfg.tdd.test_commands == [r"\bpytest\b"]

    def test_custom_test_commands(self) -> None:
        cfg = YdkConfig.model_validate({"project": {"name": "x"}, "tdd": {"test_commands": [r"\bgo test\b"]}})
        assert cfg.tdd.test_commands == [r"\bgo test\b"]

    def test_invalid_regex_rejected(self) -> None:
        with pytest.raises(ValidationError):
            YdkConfig.model_validate({"project": {"name": "x"}, "tdd": {"test_commands": ["(unclosed"]}})
