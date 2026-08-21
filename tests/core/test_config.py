"""Tests for ydk.core.config — config loading, saving, and manipulation."""

import pytest
import yaml
from pydantic import ValidationError

from ydk.core.config import (
    DEFAULT_CONFIG,
    get_config_value,
    init_config,
    load_config,
    set_config_value,
)
from ydk.models.config import YdkConfig


class TestLoadConfig:
    def test_returns_defaults_when_file_missing(self, tmp_path) -> None:
        cfg = load_config(tmp_path / "nonexistent" / "config.yaml")
        assert isinstance(cfg, YdkConfig)
        assert cfg.project.name == "my-project"

    def test_parses_valid_yaml(self, tmp_path) -> None:
        config_path = tmp_path / "config.yaml"
        data = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "name": "parsed"}}
        config_path.write_text(yaml.dump(data))
        cfg = load_config(config_path)
        assert cfg.project.name == "parsed"

    def test_rejects_invalid_yaml_unknown_fields(self, tmp_path) -> None:
        config_path = tmp_path / "config.yaml"
        data = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "name": "x"}, "bogus": True}
        config_path.write_text(yaml.dump(data))
        with pytest.raises(ValidationError, match="extra_forbidden"):
            load_config(config_path)


class TestInitConfig:
    def test_creates_file_with_defaults(self, tmp_path) -> None:
        config_path = tmp_path / ".ydk" / "config.yaml"
        cfg = init_config("new-project", config_path=config_path)
        assert cfg.project.name == "new-project"
        assert config_path.is_file()

    def test_raises_when_exists_and_not_force(self, tmp_path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing")
        with pytest.raises(FileExistsError):
            init_config("x", config_path=config_path, force=False)

    def test_with_force_overwrites(self, tmp_path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("old")
        cfg = init_config("forced", config_path=config_path, force=True)
        assert cfg.project.name == "forced"
        # Verify file was actually overwritten
        reloaded = load_config(config_path)
        assert reloaded.project.name == "forced"


class TestGetConfigValue:
    def test_dot_notation(self) -> None:
        config = {"spec_check": {"model": "my-model", "thresholds": {"completeness": 9}}}
        assert get_config_value(config, "spec_check.model") == "my-model"
        assert get_config_value(config, "spec_check.thresholds.completeness") == 9

    def test_returns_none_for_missing_key(self) -> None:
        config = {"project": {"name": "x"}}
        assert get_config_value(config, "project.nonexistent") is None
        assert get_config_value(config, "totally.missing.path") is None


class TestAwsConfigRemoved:
    def test_ydk_config_has_no_aws_field(self) -> None:
        """AwsConfig was deleted (issue #23) -- YdkConfig no longer has an ``aws`` field."""
        data = {
            **DEFAULT_CONFIG,
            "project": {**DEFAULT_CONFIG["project"], "name": "x"},
        }
        cfg = YdkConfig.model_validate(data)
        assert not hasattr(cfg, "aws")

    def test_ydk_config_rejects_aws_key(self) -> None:
        """An ``aws:`` section in config.yaml is now rejected (model_config extra='forbid')."""
        data = {
            **DEFAULT_CONFIG,
            "project": {**DEFAULT_CONFIG["project"], "name": "x"},
            "aws": {"profile": "my-profile", "region": "us-west-2"},
        }
        with pytest.raises(ValidationError):
            YdkConfig.model_validate(data)


class TestSetConfigValue:
    def test_coerces_bool(self) -> None:
        config = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "name": "x"}}
        result = set_config_value(config, "hooks.pre_push.spec_check", "true")
        assert result["hooks"]["pre_push"]["spec_check"] is True

    def test_coerces_int(self) -> None:
        config = {**DEFAULT_CONFIG, "project": {**DEFAULT_CONFIG["project"], "name": "x"}}
        result = set_config_value(config, "spec_check.timeout", "90")
        assert result["spec_check"]["timeout"] == 90

    def test_validates_result_rejects_invalid_threshold(self) -> None:
        import copy

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["project"]["name"] = "x"
        with pytest.raises(ValidationError):
            set_config_value(config, "spec_check.thresholds.completeness", "15")
