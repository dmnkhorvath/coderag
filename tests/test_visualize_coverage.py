"""Tests for coderag.cli.visualize to push coverage from 31% to 90%+.

Covers: _load_config, _open_store, visualize command (html/json, symbol, filter, auto_open).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from click.testing import CliRunner

from coderag.cli.visualize import visualize, _load_config, _open_store


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_load_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: /tmp/test\ndb_path: .codegraph/graph.db\n")
        with patch("coderag.cli.visualize.CodeGraphConfig.from_yaml") as mock_from:
            mock_from.return_value = MagicMock()
            result = _load_config(str(cfg_file))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_load_from_project_root_yaml(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.cli.visualize.CodeGraphConfig.from_yaml") as mock_from:
            mock_from.return_value = MagicMock()
            result = _load_config(None, project_root=str(tmp_path))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_load_from_project_root_yml(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yml"
        cfg_file.write_text("project_root: .\n")
        with patch("coderag.cli.visualize.CodeGraphConfig.from_yaml") as mock_from:
            mock_from.return_value = MagicMock()
            result = _load_config(None, project_root=str(tmp_path))
            mock_from.assert_called_once_with(str(cfg_file))

    def test_load_from_cwd_yaml(self, tmp_path):
        cfg_file = tmp_path / "codegraph.yaml"
        cfg_file.write_text("project_root: .\n")
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("coderag.cli.visualize.CodeGraphConfig.from_yaml") as mock_from:
                mock_from.return_value = MagicMock()
                result = _load_config(None)
                mock_from.assert_called_once()
        finally:
            os.chdir(orig_cwd)

    def test_load_default_when_no_file(self, tmp_path):
        with patch("coderag.cli.visualize.CodeGraphConfig.default") as mock_default:
            mock_default.return_value = MagicMock()
            result = _load_config(None, project_root=str(tmp_path))
            mock_default.assert_called_once()

    def test_load_explicit_path_not_exists(self, tmp_path):
        with patch("coderag.cli.visualize.CodeGraphConfig.default") as mock_default:
            mock_default.return_value = MagicMock()
            result = _load_config(str(tmp_path / "nonexistent.yaml"))
            mock_default.assert_called_once()


# ---------------------------------------------------------------------------
# _open_store
# ---------------------------------------------------------------------------

class TestOpenStore:
    def test_open_store_success(self, tmp_path):
        db_file = tmp_path / "graph.db"
        db_file.write_text("")
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(db_file)
        mock_store = MagicMock()
        with patch("coderag.cli.visualize.SQLiteStore", return_value=mock_store):
            result = _open_store(mock_config)
            assert result == mock_store
            mock_store.initialize.assert_called_once()

    def test_open_store_db_not_found(self, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "nonexistent.db")
        with pytest.raises(SystemExit):
            _open_store(mock_config)


# ---------------------------------------------------------------------------
# visualize command
# ---------------------------------------------------------------------------

class TestVisualizeCommand:
    def _make_data(self, nodes=5, edges=3):
        return {
            "metadata": {"total_nodes": nodes, "total_edges": edges},
            "nodes": [{"id": f"n{i}"} for i in range(nodes)],
            "edges": [{"source": "n0", "target": f"n{i+1}"} for i in range(edges)],
        }

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_json_format(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = str(tmp_path / "graph.json")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls:
            mock_exporter_cls.export_full.return_value = data
            result = runner.invoke(visualize, [str(tmp_path), "--format", "json", "-o", out_file], obj={})
            assert result.exit_code == 0
            assert os.path.exists(out_file)
            written = json.loads(Path(out_file).read_text())
            assert written["metadata"]["total_nodes"] == 5

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_html_format(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = tmp_path / "graph.html"
        out_file.write_text("<html></html>")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls, \
             patch("coderag.visualization.renderer.GraphRenderer") as mock_renderer_cls:
            mock_exporter_cls.export_full.return_value = data
            mock_renderer_cls.render.return_value = out_file
            result = runner.invoke(visualize, [str(tmp_path), "-o", str(out_file)], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_with_symbol(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = tmp_path / "graph.html"
        out_file.write_text("<html></html>")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls, \
             patch("coderag.visualization.renderer.GraphRenderer") as mock_renderer_cls:
            mock_exporter_cls.export_neighborhood.return_value = data
            mock_renderer_cls.render.return_value = out_file
            result = runner.invoke(visualize, [str(tmp_path), "-s", "UserService", "-d", "3", "-o", str(out_file)], obj={})
            assert result.exit_code == 0
            mock_exporter_cls.export_neighborhood.assert_called_once()

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_with_language_filter(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = tmp_path / "graph.html"
        out_file.write_text("<html></html>")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls, \
             patch("coderag.visualization.renderer.GraphRenderer") as mock_renderer_cls:
            mock_exporter_cls.export_filtered.return_value = data
            mock_renderer_cls.render.return_value = out_file
            result = runner.invoke(visualize, [str(tmp_path), "-l", "php", "-l", "javascript", "-o", str(out_file)], obj={})
            assert result.exit_code == 0
            mock_exporter_cls.export_filtered.assert_called_once()

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_with_kind_filter(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = tmp_path / "graph.json"

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls:
            mock_exporter_cls.export_filtered.return_value = data
            result = runner.invoke(visualize, [str(tmp_path), "-k", "class", "--format", "json", "-o", str(out_file)], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_auto_open(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = tmp_path / "graph.html"
        out_file.write_text("<html></html>")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls, \
             patch("coderag.visualization.renderer.GraphRenderer") as mock_renderer_cls, \
             patch("coderag.cli.visualize.webbrowser.open") as mock_open:
            mock_exporter_cls.export_full.return_value = data
            mock_renderer_cls.render.return_value = out_file
            result = runner.invoke(visualize, [str(tmp_path), "--open", "-o", str(out_file)], obj={})
            assert result.exit_code == 0
            mock_open.assert_called_once()

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_value_error(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls:
            mock_exporter_cls.export_full.side_effect = ValueError("Symbol not found")
            result = runner.invoke(visualize, [str(tmp_path), "--format", "json"], obj={})
            assert result.exit_code != 0 or "Error" in result.output

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_db_override(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = str(tmp_path / "graph.json")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls:
            mock_exporter_cls.export_full.return_value = data
            result = runner.invoke(visualize, [str(tmp_path), "--format", "json", "-o", out_file],
                                   obj={"db_override": "/custom/db.sqlite", "config_path": None})
            assert result.exit_code == 0

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_default_output_path(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        db_dir = tmp_path / ".codegraph"
        db_dir.mkdir()
        mock_config.db_path_absolute = str(db_dir / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls, \
             patch("coderag.visualization.renderer.GraphRenderer") as mock_renderer_cls:
            mock_exporter_cls.export_full.return_value = data
            out_path = db_dir / "graph.html"
            out_path.write_text("<html></html>")
            mock_renderer_cls.render.return_value = out_path
            result = runner.invoke(visualize, [str(tmp_path)], obj={})
            assert result.exit_code == 0

    @patch("coderag.cli.visualize._open_store")
    @patch("coderag.cli.visualize._load_config")
    def test_visualize_symbol_json_format(self, mock_load_config, mock_open_store, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.db_path_absolute = str(tmp_path / "graph.db")
        mock_load_config.return_value = mock_config
        mock_store = MagicMock()
        mock_open_store.return_value = mock_store

        data = self._make_data()
        out_file = str(tmp_path / "graph.json")

        with patch("coderag.visualization.exporter.GraphExporter") as mock_exporter_cls:
            mock_exporter_cls.export_neighborhood.return_value = data
            result = runner.invoke(visualize, [str(tmp_path), "-s", "Foo", "--format", "json", "-o", out_file], obj={})
            assert result.exit_code == 0
