"""Tests for coderag.core.config."""

import os
import tempfile

from coderag.core.config import CodeGraphConfig


class TestCodeGraphConfig:
    def test_default_config(self):
        config = CodeGraphConfig()
        assert config.db_path == ".codegraph/graph.db"
        assert config.max_file_size_bytes > 0

    def test_config_attributes(self):
        config = CodeGraphConfig()
        # Config should have key attributes
        assert hasattr(config, "db_path")
        assert hasattr(config, "max_file_size_bytes")
        assert hasattr(config, "enabled_languages")

    def test_from_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("db_path: custom/path.db\n")
            f.flush()
            try:
                config = CodeGraphConfig.from_yaml(f.name)
                assert config.db_path == "custom/path.db"
            finally:
                os.unlink(f.name)

    def test_to_dict(self):
        config = CodeGraphConfig()
        d = config.to_dict()
        assert isinstance(d, dict)
        assert "db_path" in d

    def test_db_path_absolute_with_project_root(self):
        config = CodeGraphConfig(project_root="/tmp/myproject")
        abs_path = config.db_path_absolute
        assert abs_path == "/tmp/myproject/.codegraph/graph.db"

    def test_db_path_absolute_already_absolute(self):
        config = CodeGraphConfig(db_path="/absolute/path.db")
        assert config.db_path_absolute == "/absolute/path.db"
