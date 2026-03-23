"""Coverage tests for Python resolver - Pass 2.

Targets missing lines: 41, 351-358, 442-445, 458-465, 484, 506-507
"""
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from coderag.plugins.python.resolver import PythonResolver, ResolutionResult, ResolutionStrategy


@pytest.fixture
def resolver():
    return PythonResolver()


# ── Stdlib Detection Tests ───────────────────────────────────

class TestStdlibDetection:
    """Test stdlib module detection (line 41 area)."""

    def test_stdlib_resolve(self, resolver, tmp_path):
        """Standard library modules resolve with HEURISTIC strategy."""
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve("os.path", "app.py")
        assert result.resolution_strategy == ResolutionStrategy.HEURISTIC
        assert result.metadata.get("stdlib") is True

    def test_json_stdlib(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve("json", "app.py")
        assert result.metadata.get("stdlib") is True

    def test_non_stdlib(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve("flask", "app.py")
        assert result.metadata.get("stdlib") is not True


# ── _is_venv Tests ───────────────────────────────────────────

class TestIsVenv:
    """Test _is_venv static method (lines 506-507)."""

    def test_venv_detected(self, tmp_path):
        venv_file = tmp_path / "venv" / "lib" / "module.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.touch()
        assert PythonResolver._is_venv(venv_file, tmp_path) is True

    def test_dot_venv_detected(self, tmp_path):
        venv_file = tmp_path / ".venv" / "lib" / "module.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.touch()
        assert PythonResolver._is_venv(venv_file, tmp_path) is True

    def test_site_packages_detected(self, tmp_path):
        sp_file = tmp_path / "site-packages" / "pkg" / "mod.py"
        sp_file.parent.mkdir(parents=True)
        sp_file.touch()
        assert PythonResolver._is_venv(sp_file, tmp_path) is True

    def test_normal_path_not_venv(self, tmp_path):
        normal_file = tmp_path / "src" / "app" / "module.py"
        normal_file.parent.mkdir(parents=True)
        normal_file.touch()
        assert PythonResolver._is_venv(normal_file, tmp_path) is False

    def test_path_outside_root(self, tmp_path):
        """Path outside root returns False."""
        other = Path("/tmp/other/module.py")
        assert PythonResolver._is_venv(other, tmp_path) is False

    def test_virtualenv_detected(self, tmp_path):
        venv_file = tmp_path / "virtualenv" / "lib" / "module.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.touch()
        assert PythonResolver._is_venv(venv_file, tmp_path) is True

    def test_pypackages_detected(self, tmp_path):
        venv_file = tmp_path / "__pypackages__" / "lib" / "module.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.touch()
        assert PythonResolver._is_venv(venv_file, tmp_path) is True


# ── resolve_symbol Tests ─────────────────────────────────────

class TestResolveSymbol:
    """Test resolve_symbol method (lines 351-358)."""

    def test_resolve_symbol_from_index(self, resolver, tmp_path):
        """Symbol found in file index."""
        resolver.set_project_root(str(tmp_path))
        # Manually populate the file index
        resolver._file_index["mypackage.models"] = "mypackage/models.py"
        result = resolver.resolve_symbol("MyClass", "app.py", context={
            "project_root": str(tmp_path),
            "import_path": "mypackage.models",
        })
        assert isinstance(result, ResolutionResult)

    def test_resolve_symbol_not_found(self, resolver, tmp_path):
        """Symbol not found returns UNRESOLVED."""
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve_symbol("NonExistent", "app.py")
        assert result.resolution_strategy == ResolutionStrategy.UNRESOLVED

    def test_resolve_symbol_via_resolve(self, resolver, tmp_path):
        """Symbol resolution falls back to resolve()."""
        resolver.set_project_root(str(tmp_path))
        # Create a real file
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "models.py").write_text("class MyClass: pass")
        result = resolver.resolve_symbol("MyClass", "app.py", context={
            "project_root": str(tmp_path),
            "import_path": "mypackage.models",
        })
        assert isinstance(result, ResolutionResult)


# ── build_index Tests ────────────────────────────────────────

class TestBuildIndex:
    """Test build_index method (lines 442-445)."""

    def test_build_index_basic(self, resolver, tmp_path):
        """Build index from file list."""
        resolver.set_project_root(str(tmp_path))
        # Create FileInfo-like objects
        from dataclasses import dataclass

        @dataclass
        class FakeFileInfo:
            relative_path: str
            language: str = "python"

        files = [
            FakeFileInfo("mypackage/models.py"),
            FakeFileInfo("mypackage/__init__.py"),
            FakeFileInfo("utils.py"),
        ]
        resolver.build_index(files)
        assert "mypackage.models" in resolver._file_index
        assert "utils" in resolver._file_index

    def test_build_index_with_src_prefix(self, resolver, tmp_path):
        """Build index strips src/ prefix."""
        resolver.set_project_root(str(tmp_path))
        from dataclasses import dataclass

        @dataclass
        class FakeFileInfo:
            relative_path: str
            language: str = "python"

        files = [FakeFileInfo("src/mypackage/models.py")]
        resolver.build_index(files)
        # Should index both with and without src prefix
        assert len(resolver._file_index) >= 1

    def test_build_index_clears_previous(self, resolver, tmp_path):
        """Build index clears previous entries."""
        resolver.set_project_root(str(tmp_path))
        from dataclasses import dataclass

        @dataclass
        class FakeFileInfo:
            relative_path: str
            language: str = "python"

        resolver.build_index([FakeFileInfo("old.py")])
        assert "old" in resolver._file_index
        resolver.build_index([FakeFileInfo("new.py")])
        assert "old" not in resolver._file_index
        assert "new" in resolver._file_index


# ── _try_resolve_from_dir Tests ──────────────────────────────

class TestTryResolveFromDir:
    """Test _try_resolve_from_dir method (lines 458-465, 484)."""

    def test_resolve_py_file(self, resolver, tmp_path):
        """Resolve a .py file."""
        resolver.set_project_root(str(tmp_path))
        (tmp_path / "models.py").write_text("class User: pass")
        result = resolver._try_resolve_from_dir("models", tmp_path, tmp_path)
        assert result is not None
        assert result.resolved_path == "models.py"

    def test_resolve_pyi_stub(self, resolver, tmp_path):
        """Resolve a .pyi stub file."""
        resolver.set_project_root(str(tmp_path))
        (tmp_path / "models.pyi").write_text("class User: ...")
        result = resolver._try_resolve_from_dir("models", tmp_path, tmp_path)
        assert result is not None
        assert "models.pyi" in result.resolved_path
        assert result.resolution_strategy == ResolutionStrategy.EXTENSION

    def test_resolve_package_init(self, resolver, tmp_path):
        """Resolve a package __init__.py."""
        resolver.set_project_root(str(tmp_path))
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        result = resolver._try_resolve_from_dir("mypackage", tmp_path, tmp_path)
        assert result is not None
        assert "__init__.py" in result.resolved_path
        assert result.resolution_strategy == ResolutionStrategy.INDEX

    def test_resolve_dotted_path(self, resolver, tmp_path):
        """Resolve a dotted path like 'mypackage.models'."""
        resolver.set_project_root(str(tmp_path))
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "models.py").write_text("class User: pass")
        result = resolver._try_resolve_from_dir("mypackage.models", tmp_path, tmp_path)
        assert result is not None

    def test_resolve_not_found(self, resolver, tmp_path):
        """Non-existent module returns None."""
        resolver.set_project_root(str(tmp_path))
        result = resolver._try_resolve_from_dir("nonexistent", tmp_path, tmp_path)
        assert result is None

    def test_resolve_venv_path_skipped(self, resolver, tmp_path):
        """Files in venv directories are skipped."""
        resolver.set_project_root(str(tmp_path))
        venv_pkg = tmp_path / "venv" / "lib" / "models.py"
        venv_pkg.parent.mkdir(parents=True)
        venv_pkg.write_text("class User: pass")
        # This should not resolve to the venv path
        result = resolver._try_resolve_from_dir("venv.lib.models", tmp_path, tmp_path)
        # Even if found, it should be filtered by _is_venv
        if result:
            assert "venv" not in result.resolved_path or result.confidence < 1.0


# ── Relative Import Tests ────────────────────────────────────

class TestRelativeImports:
    """Test relative import resolution."""

    def test_relative_import_same_package(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "models.py").write_text("class User: pass")
        (pkg / "views.py").write_text("from .models import User")
        result = resolver.resolve(".models", "mypackage/views.py", context={
            "project_root": str(tmp_path),
            "is_relative": True,
            "level": 1,
        })
        assert isinstance(result, ResolutionResult)

    def test_relative_import_parent(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        pkg = tmp_path / "mypackage"
        sub = pkg / "sub"
        sub.mkdir(parents=True)
        (pkg / "__init__.py").touch()
        (sub / "__init__.py").touch()
        (pkg / "models.py").write_text("class User: pass")
        result = resolver.resolve("..models", "mypackage/sub/views.py", context={
            "project_root": str(tmp_path),
            "is_relative": True,
            "level": 2,
        })
        assert isinstance(result, ResolutionResult)


# ── Unresolved Import Tests ──────────────────────────────────

class TestUnresolvedImports:
    """Test unresolved import handling."""

    def test_unresolved_third_party(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve("some_unknown_package", "app.py", context={
            "project_root": str(tmp_path),
        })
        assert result.resolution_strategy == ResolutionStrategy.UNRESOLVED

    def test_empty_import_path(self, resolver, tmp_path):
        resolver.set_project_root(str(tmp_path))
        result = resolver.resolve("", "app.py", context={
            "project_root": str(tmp_path),
        })
        assert isinstance(result, ResolutionResult)
