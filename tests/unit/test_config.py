"""Unit tests for config loading, env expansion, and validation."""

from __future__ import annotations

import pytest
from config_loader import BriefingConfig, expand_env_vars, load_config
from pydantic import ValidationError


class TestExpandEnvVars:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("NOPE_VAR", raising=False)
        assert expand_env_vars("${NOPE_VAR:-fallback}") == "fallback"

    def test_uses_env_value(self, monkeypatch):
        monkeypatch.setenv("SOME_VAR", "real")
        assert expand_env_vars("${SOME_VAR:-fallback}") == "real"

    def test_recurses_into_dict_and_list(self, monkeypatch):
        monkeypatch.setenv("X", "y")
        out = expand_env_vars({"a": ["${X:-z}"], "b": "${X:-z}"})
        assert out == {"a": ["y"], "b": "y"}

    def test_leaves_non_strings(self):
        assert expand_env_vars(5) == 5


class TestBriefingConfigValidation:
    def test_valid_config_passes(self, sample_config):
        model = BriefingConfig.model_validate(sample_config)
        assert model.briefing.name == "test_briefing"
        assert "us" in model.sources.apnews.sections

    def test_missing_section_field_fails(self, sample_config):
        del sample_config["sources"]["apnews"]["sections"]["us"]["max_stories"]
        with pytest.raises(ValidationError):
            BriefingConfig.model_validate(sample_config)

    def test_empty_config_fails(self):
        with pytest.raises(ValidationError):
            BriefingConfig.model_validate({})


class TestLoadConfig:
    def test_loads_and_validates_real_config(self, repo_root):
        cfg = load_config(repo_root / "config" / "daily_ap.yaml")
        assert isinstance(cfg, dict)
        assert cfg["briefing"]["name"]
        assert "apnews" in cfg["sources"]

    def test_rejects_malformed_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("briefing:\n  name: x\n")  # missing required sections
        with pytest.raises(ValidationError):
            load_config(bad)
