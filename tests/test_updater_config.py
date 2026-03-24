"""Tests for updater config module."""

from __future__ import annotations

import json

from coderag.updater.config import UpdateConfig


class TestUpdateConfigDefaults:
    """Tests for default config values."""

    def test_default_auto_check(self):
        config = UpdateConfig()
        assert config.auto_check is True

    def test_default_auto_install(self):
        config = UpdateConfig()
        assert config.auto_install is False

    def test_default_channel(self):
        config = UpdateConfig()
        assert config.channel == "stable"

    def test_default_check_interval(self):
        config = UpdateConfig()
        assert config.check_interval == 3600

    def test_default_github_repo(self):
        config = UpdateConfig()
        assert config.github_repo == "dmnkhorvath/coderag-cli"


class TestUpdateConfigLoad:
    """Tests for loading config from file."""

    def test_load_nonexistent_returns_defaults(self, tmp_path):
        config = UpdateConfig.load(tmp_path / "nonexistent.json")
        assert config.auto_check is True
        assert config.auto_install is False
        assert config.channel == "stable"

    def test_load_corrupted_json_returns_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not valid json {{{")
        config = UpdateConfig.load(path)
        assert config.auto_check is True
        assert config.channel == "stable"

    def test_load_empty_update_section(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"update": {}}))
        config = UpdateConfig.load(path)
        assert config.auto_check is True

    def test_load_partial_update_section(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"update": {"channel": "beta"}}))
        config = UpdateConfig.load(path)
        assert config.channel == "beta"
        assert config.auto_check is True  # default preserved

    def test_load_ignores_unknown_keys(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"update": {"unknown_key": "value", "channel": "dev"}}))
        config = UpdateConfig.load(path)
        assert config.channel == "dev"


class TestUpdateConfigSave:
    """Tests for saving config to file."""

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "subdir" / "config.json"
        config = UpdateConfig(channel="beta")
        config.save(path)
        assert path.exists()

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "config.json"
        config = UpdateConfig(
            auto_check=False,
            auto_install=True,
            channel="beta",
            check_interval=7200,
            github_repo="test/repo",
        )
        config.save(path)
        loaded = UpdateConfig.load(path)
        assert loaded.auto_check is False
        assert loaded.auto_install is True
        assert loaded.channel == "beta"
        assert loaded.check_interval == 7200
        assert loaded.github_repo == "test/repo"

    def test_save_preserves_existing_keys(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"other_section": {"key": "value"}}))
        config = UpdateConfig(channel="dev")
        config.save(path)
        data = json.loads(path.read_text())
        assert data["other_section"]["key"] == "value"
        assert data["update"]["channel"] == "dev"

    def test_save_all_fields_serialized(self, tmp_path):
        path = tmp_path / "config.json"
        config = UpdateConfig()
        config.save(path)
        data = json.loads(path.read_text())
        update_data = data["update"]
        assert "auto_check" in update_data
        assert "auto_install" in update_data
        assert "channel" in update_data
        assert "check_interval" in update_data
        assert "github_repo" in update_data

    def test_save_overwrites_corrupted_file(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("not valid json")
        config = UpdateConfig()
        config.save(path)
        data = json.loads(path.read_text())
        assert "update" in data
