"""Coverage tests for Flask detector - Pass 2.

Targets missing lines: 113-114, 125-126, 373, 387, 397, 429, 434-435, 438, 491
"""

from unittest.mock import MagicMock, patch

import pytest

from coderag.core.models import Node, NodeKind
from coderag.plugins.python.frameworks.flask import FlaskDetector


@pytest.fixture
def detector():
    return FlaskDetector()


# ── detect_framework Tests ───────────────────────────────────


class TestDetectFramework:
    """Test detect_framework method."""

    def test_detect_via_requirements(self, tmp_path, detector):
        """Detect Flask via requirements.txt."""
        (tmp_path / "requirements.txt").write_text("flask==2.0.0\nrequests")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_pyproject(self, tmp_path, detector):
        """Detect Flask via pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["flask"]')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_setup_py(self, tmp_path, detector):
        """Detect Flask via setup.py."""
        (tmp_path / "setup.py").write_text('install_requires=["flask"]')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_pipfile(self, tmp_path, detector):
        """Detect Flask via Pipfile."""
        (tmp_path / "Pipfile").write_text('[packages]\nflask = "*"')
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_setup_cfg(self, tmp_path, detector):
        """Detect Flask via setup.cfg."""
        (tmp_path / "setup.cfg").write_text("[options]\ninstall_requires = flask")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_app_py_import(self, tmp_path, detector):
        """Detect Flask via import in app.py (lines 125-126)."""
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_wsgi_import(self, tmp_path, detector):
        """Detect Flask via import in wsgi.py."""
        (tmp_path / "wsgi.py").write_text("import flask\napp = flask.Flask(__name__)")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_main_import(self, tmp_path, detector):
        """Detect Flask via import in main.py."""
        (tmp_path / "main.py").write_text("from flask import Flask")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_detect_via_init_import(self, tmp_path, detector):
        """Detect Flask via import in __init__.py."""
        (tmp_path / "__init__.py").write_text("from flask import Flask")
        assert detector.detect_framework(str(tmp_path)) is True

    def test_no_flask(self, tmp_path, detector):
        """No Flask detected."""
        (tmp_path / "requirements.txt").write_text("django==4.0.0")
        assert detector.detect_framework(str(tmp_path)) is False

    def test_oserror_dep_file(self, tmp_path, detector):
        """OSError reading dep file is caught (lines 113-114)."""
        (tmp_path / "requirements.txt").write_text("flask")
        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if "requirements.txt" in str(path):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            # Should continue to next file, not crash
            result = detector.detect_framework(str(tmp_path))
            assert isinstance(result, bool)

    def test_oserror_entry_point(self, tmp_path, detector):
        """OSError reading entry point file is caught (lines 125-126)."""
        (tmp_path / "app.py").write_text("from flask import Flask")
        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if "app.py" in str(path):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            result = detector.detect_framework(str(tmp_path))
            assert isinstance(result, bool)

    def test_no_files_at_all(self, tmp_path, detector):
        """Empty directory returns False."""
        assert detector.detect_framework(str(tmp_path)) is False


# ── detect_global_patterns Tests ─────────────────────────────


class TestDetectGlobalPatterns:
    """Test detect_global_patterns method (lines 373, 387, 397)."""

    def test_no_file_nodes(self, detector):
        """No FILE nodes returns empty (line 387)."""
        mock_store = MagicMock()
        mock_store.find_nodes.return_value = []
        result = detector.detect_global_patterns(mock_store)
        assert result == []

    def test_no_project_root_inferred(self, detector):
        """Cannot infer project root returns empty (line 373)."""
        mock_store = MagicMock()
        # Return FILE nodes but with paths that don't lead to a project root
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="module.py",
            qualified_name="module.py",
            file_path="/nonexistent/deep/path/module.py",
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.return_value = [file_node]
        result = detector.detect_global_patterns(mock_store)
        assert result == []

    def test_project_root_found_no_blueprints(self, detector, tmp_path):
        """Project root found but no blueprint registrations (line 491)."""
        # Create a minimal Flask project
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)")
        (tmp_path / "requirements.txt").write_text("flask")

        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="app.py",
            file_path=str(tmp_path / "app.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.return_value = [file_node]
        result = detector.detect_global_patterns(mock_store)
        assert result == []

    def test_with_blueprint_registrations(self, detector, tmp_path):
        """Blueprint registrations found (lines 429, 434-435, 438)."""
        # Create a Flask project with blueprint registration
        (tmp_path / "requirements.txt").write_text("flask")
        (tmp_path / "app.py").write_text(
            "from flask import Flask\n"
            "from blueprints import auth_bp\n"
            "app = Flask(__name__)\n"
            "app.register_blueprint(auth_bp, url_prefix='/auth')\n"
        )

        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="app.py",
            file_path=str(tmp_path / "app.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.side_effect = lambda **kwargs: {
            "kind": {
                NodeKind.FILE: [file_node],
                NodeKind.MODULE: [],
            }
        }.get("kind", {}).get(kwargs.get("kind"), [])

        # Simpler approach: use side_effect based on call count
        call_count = [0]

        def find_nodes_side_effect(**kwargs):
            call_count[0] += 1
            if kwargs.get("kind") == NodeKind.FILE:
                return [file_node]
            return []  # No matching blueprint module nodes

        mock_store.find_nodes.side_effect = find_nodes_side_effect
        result = detector.detect_global_patterns(mock_store)
        # Should find the blueprint registration
        assert len(result) == 1
        assert result[0].framework_name == "flask"
        assert result[0].pattern_type == "blueprint_registrations"

    def test_blueprint_with_oserror(self, detector, tmp_path):
        """OSError reading .py file during blueprint scan (lines 434-435)."""
        (tmp_path / "requirements.txt").write_text("flask")
        (tmp_path / "app.py").write_text("app.register_blueprint(bp)")

        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="app.py",
            file_path=str(tmp_path / "app.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.side_effect = lambda **kwargs: [file_node] if kwargs.get("kind") == NodeKind.FILE else []

        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if str(path).endswith("app.py") and "encoding" in kwargs:
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            result = detector.detect_global_patterns(mock_store)
            assert result == []

    def test_blueprint_no_register_in_content(self, detector, tmp_path):
        """File without register_blueprint is skipped (line 438)."""
        (tmp_path / "requirements.txt").write_text("flask")
        (tmp_path / "utils.py").write_text("def helper(): pass")

        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="utils.py",
            qualified_name="utils.py",
            file_path=str(tmp_path / "utils.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.side_effect = lambda **kwargs: [file_node] if kwargs.get("kind") == NodeKind.FILE else []
        result = detector.detect_global_patterns(mock_store)
        assert result == []


# ── _infer_project_root Tests ────────────────────────────────


class TestInferProjectRoot:
    """Test _infer_project_root method (lines 387, 397)."""

    def test_no_nodes(self, detector):
        """No FILE nodes returns None (line 387)."""
        mock_store = MagicMock()
        mock_store.find_nodes.return_value = []
        result = detector._infer_project_root(mock_store)
        assert result is None

    def test_no_matching_entry_files(self, detector, tmp_path):
        """No app.py/wsgi.py/requirements.txt returns None (line 397)."""
        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="random.py",
            qualified_name="random.py",
            file_path=str(tmp_path / "random.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.return_value = [file_node]
        result = detector._infer_project_root(mock_store)
        assert result is None

    def test_found_via_app_py(self, detector, tmp_path):
        """Found project root via app.py."""
        (tmp_path / "app.py").write_text("from flask import Flask")
        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="app.py",
            file_path=str(tmp_path / "app.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.return_value = [file_node]
        result = detector._infer_project_root(mock_store)
        assert result is not None

    def test_found_via_requirements(self, detector, tmp_path):
        """Found project root via requirements.txt."""
        (tmp_path / "requirements.txt").write_text("flask")
        mock_store = MagicMock()
        file_node = Node(
            id="f1",
            kind=NodeKind.FILE,
            name="models.py",
            qualified_name="models.py",
            file_path=str(tmp_path / "models.py"),
            start_line=0,
            end_line=0,
            language="python",
        )
        mock_store.find_nodes.return_value = [file_node]
        result = detector._infer_project_root(mock_store)
        assert result is not None
